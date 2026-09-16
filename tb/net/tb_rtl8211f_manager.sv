`timescale 1ns/1ps
module tb_rtl8211f_manager;
    reg clk=0;
    always #4 clk=~clk;
    reg rst_n=0;
    wire phy_rst_n,mdc,mdio_out,mdio_oe,ready,link_up,fault;
    wire [4:0] phy_address;
    tri1 mdio;
    reg phy_drive=0,phy_bit=1;
    assign mdio=mdio_oe ? mdio_out : 1'bz;
    assign mdio=phy_drive ? phy_bit : 1'bz;
    rtl8211f_manager #(.RESET_CYCLES(32),.SETTLE_CYCLES(64),
        .POLL_CYCLES(100),.RETRY_CYCLES(1000)) dut (
        .clk(clk),.rst_n(rst_n),.phy_rst_n(phy_rst_n),.mdc(mdc),
        .mdio_out(mdio_out),.mdio_oe(mdio_oe),.mdio_in(mdio),
        .ready(ready),.link_up(link_up),.fault(fault),.phy_address(phy_address));

    reg present=1,corrupt_rx_write=0,corrupt_eee_write=0,wrong_model=0;
    reg [4:0] model_address=5;
    reg [15:0] model_status=16'h102c;
    reg [15:0] page,tx_cfg,rx_cfg,anar,gbcr,bmcr,mmd_control,mmd_address,eee_advertisement;
    reg [31:0] scan_seen=0;
    integer frame_bit=0,transactions=0,writes=0,reads=0,resets=0;
    reg [13:0] header;
    reg [15:0] write_word,response_word;
    reg [1:0] command;
    reg [4:0] address,register_number;
    reg response_enable;
    time reset_asserted,reset_released,last_mdc_edge=0;
    time last_mdc_rise=0;
    reg have_edge=0;
    integer checks=0;

    task automatic check(input bit okay,input string detail);
        begin
            checks=checks+1;
            if (!okay) begin
                $display("[TB_ERROR] %s at %0t",detail,$time);
                $fatal(1,"PHY manager verification failed");
            end
        end
    endtask

    function automatic [15:0] read_register(input [4:0] n);
        begin
            case(n)
                0: read_register=bmcr;
                2: read_register=16'h001c;
                3: read_register=wrong_model ? 16'hc915 : 16'hc916;
                4: read_register=anar;
                9: read_register=gbcr;
                14: read_register=(mmd_control==16'h4007 && mmd_address==16'h003c) ? eee_advertisement : 16'hffff;
                17: read_register=page==16'h0d08 ? tx_cfg : 16'hffff;
                21: read_register=page==16'h0d08 ? rx_cfg : 16'hffff;
                26: read_register=page==16'h0a43 ? model_status : 16'hffff;
                31: read_register=page;
                default: read_register=16'hffff;
            endcase
        end
    endfunction

    task automatic write_register(input [4:0] n,input [15:0] value);
        begin
            writes=writes+1;
            case(n)
                0: begin
                    check((value & 16'h001f)==(bmcr & 16'h001f),"BMCR reserved bits changed");
                    check((eee_advertisement & 16'h0006)==0,"EEE still advertised at auto-negotiation restart");
                    bmcr=value & 16'hfdff; // Restart_AN self clears.
                end
                4: begin
                    check((value & ~16'hade0)==(anar & ~16'hade0),"ANAR unrelated bits changed");
                    anar=value;
                end
                9: begin
                    check((value & ~16'hf200)==(gbcr & ~16'hf200),"GBCR reserved/unrelated bits changed");
                    gbcr=value;
                end
                13: begin
                    check(value==0 || value==16'h0007 || value==16'h4007,"Invalid MMD control command");
                    mmd_control=value;
                end
                14: begin
                    if(mmd_control==16'h0007) mmd_address=value;
                    else begin
                        check(mmd_control==16'h4007 && mmd_address==16'h003c,"EEE advertisement written to wrong MMD register");
                        check((value & ~16'h0006)==(eee_advertisement & ~16'h0006),"EEE reserved bits changed");
                        eee_advertisement=corrupt_eee_write ? (value | 16'h0006) : value;
                    end
                end
                17: begin
                    check(page==16'h0d08,"TX delay written on wrong page");
                    check((value & ~16'h0100)==(tx_cfg & ~16'h0100),"TX delay RMW changed unrelated bits");
                    tx_cfg=value;
                end
                21: begin
                    check(page==16'h0d08,"RX delay written on wrong page");
                    check((value & ~16'h0008)==(rx_cfg & ~16'h0008),"RX delay RMW changed unrelated bits");
                    rx_cfg=corrupt_rx_write ? (value & 16'hfff7) : value;
                end
                31: page=value;
                default: check(0,"Unexpected/reserved register write");
            endcase
        end
    endtask

    // Independent PHY model decodes only the actual MDC/MDIO pins. Output data
    // is driven 300 ns after the MDC rising edge (datasheet maximum t6), rather
    // than the often-used zero-delay/falling-edge model that hides TA bugs.
    always @(negedge phy_rst_n or negedge rst_n) begin
        reset_asserted=$time;
        page=0;tx_cfg=16'h5a25;rx_cfg=16'hac50;
        anar=16'h4de1;gbcr=16'h1905;bmcr=16'h6c15;
        mmd_control=0;mmd_address=0;eee_advertisement=16'ha506;
        phy_drive=0;phy_bit=1;
        have_edge=0;
        frame_bit=0;
    end
    always @(posedge phy_rst_n) begin
        reset_released=$time;
        resets=resets+1;
        check($time-reset_asserted>=32*8,"PHY reset too short");
    end
    always @(posedge mdio_oe) begin
        check(!phy_drive,"MAC took MDIO while PHY drives");
        frame_bit=0;
        header=0;
        write_word=0;
        transactions=transactions+1;
    end
    always @(posedge mdc) begin
        check(phy_rst_n,"MDIO transaction during hardware reset");
        check($time-reset_released>=64*8,"MDIO transaction before settle completes");
        if(have_edge) check($time-last_mdc_rise>=400,"MDC exceeds 2.5 MHz");
        last_mdc_rise=$time;
        have_edge=1;
        check(!(phy_drive && mdio_oe),"MDIO pad contention");
        if(frame_bit<32) check(mdio_oe && mdio===1'b1,"Preamble is not 32 driven ones");
        if(frame_bit>=32 && frame_bit<=45) begin
            check(mdio_oe,"Header bit not driven by MAC");
            header={header[12:0],mdio};
            if(frame_bit==45) begin
                check(header[13:12]==2'b01,"Invalid Clause22 ST field");
                command=header[11:10];
                address=header[9:5];
                register_number=header[4:0];
                check(command==2'b01 || command==2'b10,"Invalid Clause22 OP field");
                response_enable=present && (address==0 || address==model_address || address==1);
                response_word=read_register(register_number);
                // Another vendor revision responds at address1; must be rejected.
                if(address==1 && model_address!=1 && register_number==3)
                    response_word=16'hc915;
                if(command==2'b10) begin
                    reads=reads+1;
                    if(register_number==2) scan_seen[address]=1'b1;
                end
            end
        end
        if(frame_bit>=46 && command==2'b10) begin
            check(!mdio_oe,"MAC failed to release read turnaround/data");
            if(frame_bit==46) begin
                check(!phy_drive,"PHY did not release first turnaround interval");
                phy_drive<=#300 response_enable;
                phy_bit<=#300 1'b0;
            end else if(frame_bit<=62) begin
                phy_bit<=#300 response_word[62-frame_bit];
            end else begin
                phy_drive<=#300 1'b0;
            end
        end
        if(frame_bit>=46 && command==2'b01) begin
            if(frame_bit==46) check(mdio_oe && mdio===1'b1,"Write TA first bit must be one");
            if(frame_bit==47) check(mdio_oe && mdio===1'b0,"Write TA second bit must be zero");
            if(frame_bit>=48 && frame_bit<=63) begin
                check(mdio_oe,"Write data not driven");
                write_word={write_word[14:0],mdio};
                if(frame_bit==63 && response_enable) begin
                    check(address==model_address,"Configuration used broadcast or wrong PHY");
                    write_register(register_number,write_word);
                end
            end
            if(frame_bit==64) check(!mdio_oe,"Write idle not released");
        end
        frame_bit=frame_bit+1;
    end

    task automatic reset_case;
        begin
            @(negedge clk);rst_n=0;
            repeat(8) @(negedge clk);
            scan_seen=0;
            rst_n=1;
        end
    endtask
    task automatic wait_ready;
        integer n;
        begin
            n=0;
            while(!ready && n<1000000) begin @(negedge clk);n=n+1;end
            check(ready,"Timeout waiting for configuration readiness");
        end
    endtask
    task automatic wait_link(input bit expected);
        integer n;
        begin
            n=0;
            while(link_up!==expected && n<30000) begin @(negedge clk);n=n+1;end
            check(link_up===expected,"Timeout waiting for link status");
            // Allow a second complete poll to reject a transient lucky sample.
            repeat(18000) @(negedge clk);
            check(link_up===expected,"Link status did not remain correct");
        end
    endtask
    task automatic wait_fault;
        integer n;
        begin
            n=0;
            while(!fault && n<1000000) begin @(negedge clk);n=n+1;end
            check(fault && !ready && !link_up,"Failure did not fail closed");
        end
    endtask

    wire production_timing_done;
    phy_production_reset_check production_check(.done(production_timing_done));
    initial begin
        reset_case();
        wait_ready();
        check(phy_address==5,"Did not scan nondefault PHY address past broadcast zero");
        check(!fault,"Unexpected startup fault");
        check((scan_seen & 32'h3f)==32'h3f,"Address scan skipped 0..5");
        check(tx_cfg==16'h5b25 && rx_cfg==16'hac58,"RGMII delays not enabled or RMW corrupted data");
        check(anar==16'h4001,"10/100/PAUSE advertisement was not cleared");
        check(gbcr==16'h0b05,"Gigabit full duplex / automatic master-slave configuration wrong");
        check(eee_advertisement==16'ha500,"EEE disable or reserved-bit preservation failed");
        check((bmcr & 16'hfde0)==16'h1140,"BMCR autonegotiation configuration wrong");
        wait_link(1);
        $display("[TB_DATA] address5 scan, broadcast handling, ID model match, configuration RMW/readback PASS");

        model_status=16'h101c;wait_link(0);check(ready,"100M must not destroy initialization readiness");
        model_status=16'h100c;wait_link(0);
        model_status=16'h1024;wait_link(0);
        model_status=16'h102c;wait_link(1);
        model_status=16'h1028;wait_link(0);
        model_status=16'h102c;wait_link(1);
        check(!fault,"Ordinary link down incorrectly set fault");
        $display("[TB_DATA] 100M/10M/half-duplex rejection and cable-loss recovery PASS");

        present=0;wait_fault();
        present=1;wait_ready();wait_link(1);
        check(fault,"Runtime MDIO error fault was not sticky across recovery");
        check(resets>=2,"Runtime MDIO loss did not retry full hardware startup");
        $display("[TB_DATA] runtime missing-ACK fail-closed and automatic retry PASS");

        corrupt_rx_write=1;reset_case();wait_fault();
        check(!rx_cfg[3],"Readback-failure stimulus ineffective");
        $display("[TB_DATA] corrupted RGMII RX delay write rejected by readback PASS");

        corrupt_rx_write=0;corrupt_eee_write=1;reset_case();wait_fault();
        check(eee_advertisement[2:1]==2'b11,"EEE readback-failure stimulus ineffective");
        $display("[TB_DATA] EEE MMD7 RMW and rejected EEE write detected before autonegotiation PASS");

        corrupt_eee_write=0;present=0;reset_case();wait_fault();
        check(scan_seen==32'hffffffff,"No-device case did not scan all32 PHY addresses");
        $display("[TB_DATA] no-PHY/undriven turnaround scan0..31 failure PASS");

        present=1;wrong_model=1;reset_case();wait_fault();
        check(scan_seen==32'hffffffff,"Wrong-PHY case did not scan full range");
        $display("[TB_DATA] RTL8211E ID rejected; no undocumented configuration attempted PASS");

        wrong_model=0;model_address=7;reset_case();wait_ready();wait_link(1);
        check(phy_address==7 && !fault,"Reset recovery/address7 failed");
        @(negedge clk);rst_n=0;
        repeat(5) @(negedge clk);
        check(!ready && !link_up && !fault && !phy_rst_n && !mdio_oe && !mdc,"Reset did not clear outputs");
        wait(production_timing_done);
        $display("[TB_DATA] checks=%0d transactions=%0d reads=%0d writes=%0d resets=%0d",checks,transactions,reads,writes,resets);
        $display("[TB_INFO] Simulation Finished!");
        $finish;
    end
    initial begin
        #100000000;
        $fatal(1,"[TB_ERROR] Global timeout");
    end
endmodule

// Exercise real 20 ms reset / 50 ms settling default durations, at a slower
// declared and actual system clock to keep the simulation small. No timing
// parameters other than CLK_HZ are overridden.
module phy_production_reset_check(output reg done=0);
    reg clk=0,rst_n=0;
    always #500 clk=~clk;
    wire phy_rst_n,mdc,mdio_out,mdio_oe,ready,link_up,fault;
    wire [4:0] phy_address;
    time released;
    rtl8211f_manager #(.CLK_HZ(1000000)) dut (
        .clk(clk),.rst_n(rst_n),.phy_rst_n(phy_rst_n),.mdc(mdc),
        .mdio_out(mdio_out),.mdio_oe(mdio_oe),.mdio_in(1'b1),
        .ready(ready),.link_up(link_up),.fault(fault),.phy_address(phy_address));
    initial begin
        #10;rst_n=1;
        @(posedge phy_rst_n);
        if($time<19999500) $fatal(1,"[TB_ERROR] Production reset shorter than20 ms");
        released=$time;
        @(posedge mdc);
        if($time-released<50000000) $fatal(1,"[TB_ERROR] Production settle shorter than50 ms");
        $display("[TB_DATA] Production default reset20 ms and post-reset settle50 ms PASS");
        done=1;
    end
endmodule
