`timescale 1ns/1ps
// Complete board RTL + real MDIO controller/PHY manager + pin-level PHY BFM.
// Only clock/DDR primitives are digital stubs; vendor primitives have a separate test.
module tb_system_uart;
    reg ref_clk=0,eth_clk=0,rx_clk=0,rx_run=1;
    always #18.5185185 ref_clk=~ref_clk;
    always #4 eth_clk=~eth_clk;
    always #4.017 if(rx_run)rx_clk=~rx_clk;
    wire audio_clk=dut.audio_clk;
    reg reset_n=0,uart_rx=1;
    wire uart_tx;
    wire [7:0] mic_clk;
    wire [3:0] txd;wire [4:0] led;
    wire txc,txctl,mdc,phy_rst_n;
    tri1 mdio;
    wire mdio_oe=dut.mdio_oe;
    reg phy_drive=0,phy_bit=1;
    assign mdio=phy_drive?phy_bit:1'bz;
    reg [7:0] gmii_rxd=0;reg gmii_rx_dv=0;
    mems_array_pg2l200h #(.KEY_DEBOUNCE_CYCLES(8),.SELFTEST_FRAMES(16),.SELFTEST_TX_PACKETS(4),
        .STARTUP_CYCLES(1024),.UART_DIV(8),.UART_REPORT_CYCLES(27000),.UART_MS_CYCLES(27000),
        .UART_RESET_CYCLES(32400),.UART_MODE_CYCLES(2700),.UART_WINDOW_CYCLES(2700),.UART_PRESCALE_BITS(6)) dut(
        .sys_clk_27(ref_clk),.sys_clk_125_p(eth_clk),.sys_clk_125_n(~eth_clk),.reset_n(reset_n),
        .selftest_key_n(1'b1),.uart_rx(uart_rx),.uart_tx(uart_tx),.led(led),.pdm_data(64'b0),
        .mic_clk(mic_clk),.PHY0_RXC(rx_clk),.PHY0_RXCTRL(1'b0),.PHY0_RXD(4'b0),
        .PHY0_TXC(txc),.PHY0_TXCTRL(txctl),.PHY0_TXD(txd),.PHY0_MDC(mdc),.PHY0_MDIO(mdio),.RSTN_OUT(phy_rst_n));
    defparam dut.phy.RESET_CYCLES=32,dut.phy.SETTLE_CYCLES=64,dut.phy.POLL_CYCLES=100,dut.phy.RETRY_CYCLES=1000;
    integer checks=0,lines=0,raw_file,tx_count=0,arp_count=0,udp_count=0;
    reg [31:0] words[0:33];
    byte unsigned tx_frame[0:1599],arp[0:63];
    reg was_en=0,suppress_abort=0;
    task automatic check(input bit okay,input string detail);
        begin checks++;if(!okay)$fatal(1,"[TB_ERROR] %s time=%0t",detail,$time);end
    endtask
    task automatic send_command(input byte value);
        integer i;
        begin
            @(negedge ref_clk);uart_rx=0;repeat(8)@(negedge ref_clk);
            for(i=0;i<8;i++)begin uart_rx=value[i];repeat(8)@(negedge ref_clk);end
            uart_rx=1;repeat(12)@(negedge ref_clk);
        end
    endtask
    string line="",token;
    reg [7:0] byte_value;integer bi,wi,n;
    initial forever begin
        @(negedge uart_tx);repeat(4)@(posedge ref_clk);check(uart_tx===0,"UART start");
        for(bi=0;bi<8;bi++)begin repeat(8)@(posedge ref_clk);byte_value[bi]=uart_tx;end
        repeat(8)@(posedge ref_clk);check(uart_tx===1,"UART stop");
        if(byte_value==10)begin
            check(line.len()==311,"SYS3 fixed line length");
            check(line.substr(0,4)=="SYS3 ","SYS3 identifier");
            for(wi=0;wi<34;wi++)begin
                token=line.substr(5+wi*9,12+wi*9);
                n=$sscanf(token,"%h",words[wi]);check(n==1 && !$isunknown(words[wi]),"UART defined hex word");
                if(wi<33)check(line.getc(13+wi*9)==32,"UART word separator");
            end
            check(line.getc(310)==13,"UART CRLF");
            check(words[0]==lines,"UART consecutive sequence");
            $fwrite(raw_file,"%s\n",line);lines++;line="";
        end else line={line,byte_value};
    end
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
    integer phy_checks=0;

    task automatic phy_check(input bit okay,input string detail);
        begin
            phy_checks=phy_checks+1;
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
                    phy_check((value & 16'h001f)==(bmcr & 16'h001f),"BMCR reserved bits changed");
                    phy_check((eee_advertisement & 16'h0006)==0,"EEE still advertised at auto-negotiation restart");
                    bmcr=value & 16'hfdff; // Restart_AN self clears.
                end
                4: begin
                    phy_check((value & ~16'hade0)==(anar & ~16'hade0),"ANAR unrelated bits changed");
                    anar=value;
                end
                9: begin
                    phy_check((value & ~16'hf200)==(gbcr & ~16'hf200),"GBCR reserved/unrelated bits changed");
                    gbcr=value;
                end
                13: begin
                    phy_check(value==0 || value==16'h0007 || value==16'h4007,"Invalid MMD control command");
                    mmd_control=value;
                end
                14: begin
                    if(mmd_control==16'h0007) mmd_address=value;
                    else begin
                        phy_check(mmd_control==16'h4007 && mmd_address==16'h003c,"EEE advertisement written to wrong MMD register");
                        phy_check((value & ~16'h0006)==(eee_advertisement & ~16'h0006),"EEE reserved bits changed");
                        eee_advertisement=corrupt_eee_write ? (value | 16'h0006) : value;
                    end
                end
                17: begin
                    phy_check(page==16'h0d08,"TX delay written on wrong page");
                    phy_check((value & ~16'h0100)==(tx_cfg & ~16'h0100),"TX delay RMW changed unrelated bits");
                    tx_cfg=value;
                end
                21: begin
                    phy_check(page==16'h0d08,"RX delay written on wrong page");
                    phy_check((value & ~16'h0008)==(rx_cfg & ~16'h0008),"RX delay RMW changed unrelated bits");
                    rx_cfg=corrupt_rx_write ? (value & 16'hfff7) : value;
                end
                31: page=value;
                default: phy_check(0,"Unexpected/reserved register write");
            endcase
        end
    endtask

    // Independent PHY model decodes only the actual MDC/MDIO pins. Output data
    // is driven 300 ns after the MDC rising edge (datasheet maximum t6), rather
    // than the often-used zero-delay/falling-edge model that hides TA bugs.
    always @(negedge phy_rst_n or negedge reset_n) begin
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
        phy_check($time-reset_asserted>=32*8,"PHY reset too short");
    end
    always @(posedge mdio_oe) begin
        phy_check(!phy_drive,"MAC took MDIO while PHY drives");
        frame_bit=0;
        header=0;
        write_word=0;
        transactions=transactions+1;
    end
    always @(posedge mdc) begin
        phy_check(phy_rst_n,"MDIO transaction during hardware reset");
        phy_check($time-reset_released>=64*8,"MDIO transaction before settle completes");
        if(have_edge) phy_check($time-last_mdc_rise>=400,"MDC exceeds 2.5 MHz");
        last_mdc_rise=$time;
        have_edge=1;
        phy_check(!(phy_drive && mdio_oe),"MDIO pad contention");
        if(frame_bit<32) phy_check(mdio_oe && mdio===1'b1,"Preamble is not 32 driven ones");
        if(frame_bit>=32 && frame_bit<=45) begin
            phy_check(mdio_oe,"Header bit not driven by MAC");
            header={header[12:0],mdio};
            if(frame_bit==45) begin
                phy_check(header[13:12]==2'b01,"Invalid Clause22 ST field");
                command=header[11:10];
                address=header[9:5];
                register_number=header[4:0];
                phy_check(command==2'b01 || command==2'b10,"Invalid Clause22 OP field");
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
            phy_check(!mdio_oe,"MAC failed to release read turnaround/data");
            if(frame_bit==46) begin
                phy_check(!phy_drive,"PHY did not release first turnaround interval");
                phy_drive<=#300 response_enable;
                phy_bit<=#300 1'b0;
            end else if(frame_bit<=62) begin
                phy_bit<=#300 response_word[62-frame_bit];
            end else begin
                phy_drive<=#300 1'b0;
            end
        end
        if(frame_bit>=46 && command==2'b01) begin
            if(frame_bit==46) phy_check(mdio_oe && mdio===1'b1,"Write TA first bit must be one");
            if(frame_bit==47) phy_check(mdio_oe && mdio===1'b0,"Write TA second bit must be zero");
            if(frame_bit>=48 && frame_bit<=63) begin
                phy_check(mdio_oe,"Write data not driven");
                write_word={write_word[14:0],mdio};
                if(frame_bit==63 && response_enable) begin
                    phy_check(address==model_address,"Configuration used broadcast or wrong PHY");
                    write_register(register_number,write_word);
                end
            end
            if(frame_bit==64) phy_check(!mdio_oe,"Write idle not released");
        end
        frame_bit=frame_bit+1;
    end

    function automatic [31:0] crc_step(input [31:0] old,input [7:0] b);
        reg [31:0] c;reg feedback;integer i;
        begin
            c=old;
            for(i=0;i<8;i=i+1) begin feedback=c[31]^b[i];c=c<<1;if(feedback)c=c^32'h04c11db7;end
            crc_step=c;
        end
    endfunction
    function automatic [31:0] crc_finish(input [31:0] c);
        integer i;begin for(i=0;i<32;i=i+1)crc_finish[i]=~c[31-i];end
    endfunction
    task automatic arp_reply;
        integer i;reg [31:0] c,v;
        reg [47:0] lm,pm;
        begin
            lm=48'h020000000128;pm=48'h102030405060;
            for(i=0;i<64;i=i+1)arp[i]=0;
            for(i=0;i<6;i=i+1)begin
                arp[i]=lm>>((5-i)*8);arp[6+i]=pm>>((5-i)*8);
                arp[22+i]=pm>>((5-i)*8);arp[32+i]=lm>>((5-i)*8);
            end
            arp[12]=8'h08;arp[13]=6;arp[15]=1;arp[16]=8'h08;
            arp[18]=6;arp[19]=4;arp[21]=2;
            arp[28]=192;arp[29]=168;arp[30]=10;arp[31]=1;
            arp[38]=192;arp[39]=168;arp[40]=10;arp[41]=2;
            c='1;for(i=0;i<60;i=i+1)c=crc_step(c,arp[i]);v=crc_finish(c);
            for(i=0;i<4;i=i+1)arp[60+i]=v>>(i*8);
            for(i=0;i<8;i=i+1)begin @(negedge rx_clk);gmii_rx_dv=1;gmii_rxd=(i==7)?8'hd5:8'h55;end
            for(i=0;i<64;i=i+1)begin @(negedge rx_clk);gmii_rxd=arp[i];end
            @(negedge rx_clk);gmii_rx_dv=0;
        end
    endtask

    always @(negedge eth_clk)begin:monitor_wire
        integer i;reg [31:0] c;
        if(!dut.eth_rst_n || !dut.link_up)was_en=0;
        if(dut.tx_en)begin
            if(!was_en)tx_count=0;tx_frame[tx_count]=dut.tx_data;tx_count++;
        end else if(was_en && !suppress_abort)begin
            check(tx_count>=72,"complete Ethernet frame");
            c='1;for(i=8;i<tx_count-4;i++)c=crc_step(c,tx_frame[i]);c=crc_finish(c);
            for(i=0;i<4;i++)check(tx_frame[tx_count-4+i]==((c>>(8*i))&255),"wire FCS");
            if({tx_frame[20],tx_frame[21]}==16'h0806)arp_count++;
            else begin check(tx_count==1262,"UDP wire length");udp_count++;end
        end
        was_en=dut.tx_en;
    end
    integer prior_lines,prior_arp;
    initial begin
        raw_file=$fopen("../log/system_uart/rtl_uart.log","w");check(raw_file!=0,"UART log open");
        force dut.rx_data=gmii_rxd;force dut.rx_dv=gmii_rx_dv;
        repeat(10)@(negedge ref_clk);reset_n=1;
        wait(dut.calibration_done);send_command("t");wait(dut.selftest_mode);
        wait(dut.phy_ready && dut.link_up);
        wait(arp_count>0);
        #2000000;
        check(!dut.core.acquisition_active && !dut.core.overflow && dut.core.dropped_frames==0,
            "delayed ARP must hold acquisition and preserve all startup frames");
        arp_reply();wait(udp_count>=8);
        wait(words[25]>=4 && words[13]==32'h001cc916 && words[7][2:0]==7);
        check(words[12][15:14]==3 && words[20]==16'h102c,"PHY ready/link/status in UART");
        check(words[22]>=1 && words[24]>=1 && words[28]==32'h30405060 && words[29]==16'h1020,"ARP counts and resolved MAC in UART");
        check(words[30]>=1 && words[31]==0 && words[32]>=72,"RX frame/error/byte counts");
        check(words[8][7] && !words[8][8],"local BIST pass without fail");
        check(words[21][13] && !words[21][14],"UDP BIST pass without fail");
        check(words[25]<=udp_count && words[26]<=udp_count+arp_count,"counters correspond to completed wire frames");
        $display("[TB_DATA] UART PHY ID/config/PHYSR -> ARP peer MAC -> UDP and PDM BIST PASS");
        wait(dut.core.network.state==2 && dut.core.network.body_index==100);
        prior_arp=arp_count;suppress_abort=1;send_command("t");wait(!dut.selftest_mode);
        wait(dut.core.acquisition_active);repeat(10)@(negedge eth_clk);suppress_abort=0;
        check(!dut.core.tx_error,"mode change poisoned new stream TX status");
        repeat(3000)@(negedge ref_clk); // let the prior virtual key release and debounce
        send_command("t");wait(dut.selftest_mode);wait(dut.core.acquisition_active);
        wait(dut.selftest_tx_pass && dut.selftest_pass);
        check(arp_count==prior_arp && dut.core.network.peer_valid,"mode switch must retain resolved peer without another ARP");
        check(!dut.core.overflow && dut.core.dropped_frames==0,"mode switch startup frames lost");
        check(!dut.selftest_tx_fail && !dut.selftest_fail,"running-mode BIST restart retained old fault");
        $display("[TB_DATA] UART mode switch during active UDP, new session BIST PASS");
        rx_run=0;prior_lines=lines;wait(lines>=prior_lines+3);
        check(words[7][2:0]==3,"stopped RX clock marked stale, other snapshots live");
        rx_run=1;wait(words[7][2:0]==7);
        $display("[TB_DATA] Stopped RX domain cannot stall UART; recovery snapshot PASS");
        present=0;wait(dut.phy_fault);wait(words[18]>0);
        check(words[19][31:28]==11 && !words[19][21],"MDIO poll no-ACK cause retained");
        check(words[17]>0 && words[12][16],"MDIO noACK/fault telemetry");
        present=1;wait(dut.phy_ready && dut.link_up);
        wait(words[12][15:14]==3);
        $display("[TB_DATA] MDIO no-ACK failure, saved step/data and automatic recovery PASS");
        send_command("r");wait(words[2][27]);
        check(words[5][15:0]==4 && words[5][23:16]==8'h72,"UART reset acknowledgement");
        wait(dut.calibration_done);check(!dut.selftest_mode,"software reset clears mode");
        wait(!words[2][27] && words[2][5:0]==6'h3f);
        send_command("c");send_command("s");wait(words[5][15:0]==6);
        check(words[6]==0,"UART RX errors and unknown commands zero");
        check(words[2][22:15]==0,"no current/sticky clock fault after recovery");
        $fclose(raw_file);
        $display("[TB_INFO] UART integration lines=%0d checks=%0d PHY_checks=%0d",lines,checks,phy_checks);
        $display("[TB_INFO] Simulation Finished!");$finish;
    end
    initial begin #40000000;$fatal(1,"[TB_ERROR] UART integration timeout");end
endmodule

module pango_board_clocks(input wire ref_clk_27,ref_clk_125_p,ref_clk_125_n,rst_n,
    output wire audio_clk,eth_clk,locked,monitor_ref_clk,monitor_raw125_clk,monitor_clk96,
    output wire [2:0] monitor_locks);
    reg a=0,b=0;
    always #4.0690104167 a=~a;
    always #5.2083333333 b=~b;
    assign audio_clk=a;assign eth_clk=ref_clk_125_p;assign locked=rst_n;
    assign monitor_ref_clk=ref_clk_27;assign monitor_raw125_clk=ref_clk_125_p;
    assign monitor_clk96=b;assign monitor_locks={3{rst_n}};
endmodule
module GTP_DFF #(parameter GRS_EN="TRUE",parameter INIT=1'b0)(input wire CLK,D,output reg Q=INIT);
    always @(posedge CLK)Q<=D;
endmodule
module pango_rgmii_io(input wire tx_clk,rst_n,input wire [7:0] tx_data,
    input wire tx_en,tx_er,rgmii_rxc,rgmii_rx_ctl,input wire [3:0] rgmii_rxd,
    output wire rx_clk,output wire [7:0] rx_data,output wire rx_dv,rx_er,
    output wire rgmii_txc,rgmii_tx_ctl,output wire [3:0] rgmii_txd);
    assign rx_clk=rgmii_rxc;assign rx_data=0;assign rx_dv=0;assign rx_er=0;
    assign rgmii_txc=tx_clk;assign rgmii_tx_ctl=tx_en;assign rgmii_txd=tx_data[3:0];
endmodule
