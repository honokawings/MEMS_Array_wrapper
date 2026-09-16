`timescale 1ns/1ps
// Real board top + core + front end. Only physical clock/RGMII/PHY wrappers
// are replaced below, so this test checks the actual calibration storage and
// all reset/stream/FIFO integration without a 50 ms microphone acquisition.
module tb_board_boot;
    reg audio_clk=0,eth_clk=0,rx_clk=0,run_audio_clock=1;
    always #4.069 if(run_audio_clock) audio_clk=~audio_clk;
    always #4 eth_clk=~eth_clk;
    always #4.2 rx_clk=~rx_clk;
    reg reset_n=0;
    wire [3:0] mic_clk,txd;
    wire txc,txctl,mdc,phy_reset;
    tri1 mdio;
    mems_array_pg2l200h dut(.sys_clk_27(audio_clk),.sys_clk_125_p(eth_clk),
        .sys_clk_125_n(~eth_clk),.reset_n(reset_n),.pdm_data(64'd0),
        .mic_clk(mic_clk),.PHY0_RXC(rx_clk),.PHY0_RXCTRL(1'b0),.PHY0_RXD(4'd0),
        .PHY0_TXC(txc),.PHY0_TXCTRL(txctl),.PHY0_TXD(txd),.PHY0_MDC(mdc),
        .PHY0_MDIO(mdio),.RSTN_OUT(phy_reset));
    integer checks=0,boot_writes=0,total_writes=0,starts=0;

    task automatic check(input bit okay,input string detail);
        begin
            checks=checks+1;
            if(!okay) begin
                $display("[TB_ERROR] %s at %0t",detail,$time);
                $fatal(1,"Board boot verification failed");
            end
        end
    endtask

    always @(posedge audio_clk) begin
        if(!dut.audio_rst_n) boot_writes=0;
        else if(dut.core.cfg_valid && dut.core.cfg_ready) begin
            check(dut.core.audio_rst_n,"Calibration acknowledged while actual front end is in reset");
            check(!dut.core.acquisition_active,"Calibration overlaps acquisition");
            check(dut.cfg_channel==boot_writes,"Calibration channel was skipped or repeated");
            boot_writes=boot_writes+1;total_writes=total_writes+1;
        end
    end
    always @(posedge dut.core.acquisition_active) begin
        starts=starts+1;
        check(boot_writes==128 && dut.calibration_done,"Acquisition started before all128 coefficients were written");
    end

    task automatic wait_boot;
        integer n,c;
        begin
            n=0;
            while(!dut.calibration_done && n<200) begin @(negedge audio_clk);n=n+1;end
            check(dut.calibration_done && boot_writes==128,"Boot did not complete exactly128 writes");
            for(c=0;c<128;c=c+1) begin
                check(dut.core.frontend.calibration.gain[c]==24'sd4000000,"Nonunity calibration gain missing");
                check(dut.core.frontend.calibration.offset[c]==32'sd12345,"Nonzero calibration offset missing");
            end
        end
    endtask
    task automatic wait_active;
        integer n;
        begin
            n=0;
            while(!dut.core.acquisition_active && n<20) begin @(negedge audio_clk);n=n+1;end
            check(dut.core.acquisition_active,"Audio stream reset did not release");
            repeat(10) @(negedge eth_clk);
        end
    endtask

    initial begin
        // Non-default values expose a silently dropped channel0 write.
        force dut.cfg_gain=24'sd4000000;
        force dut.cfg_offset=32'sd12345;
        // Model independent synchronizers resolving reset deassertion three
        // clocks apart. The true core reset must gate the acknowledgement.
        force dut.core.audio_rst_n=1'b0;
        repeat(8) @(negedge eth_clk);
        dut.phy.requested_link=1;
        dut.clocks.test_locked=1;
        reset_n=1;
        wait(dut.audio_rst_n);
        repeat(3) @(negedge audio_clk);
        check(dut.cfg_channel==0 && boot_writes==0 && !dut.cfg_ready,
              "Delayed core reset lost initial configuration writes");
        release dut.core.audio_rst_n;
        wait_boot();wait_active();
        check(dut.core.stream_epoch==1,"Initial stream epoch must be1");
        check(mic_clk[0]===mic_clk[1] && mic_clk[1]===mic_clk[2] && mic_clk[2]===mic_clk[3],
              "Replicated microphone clocks are not identical");
        $display("[TB_DATA] Board/core reset skew3 clocks, nonunity coefficient0..127, calibration before acquisition PASS");

        // Stop audio clock, then lose link. Async reset assertion must not wait
        // for a clock; pointers in BOTH domains must clear immediately.
        @(negedge audio_clk);run_audio_clock=0;
        dut.phy.requested_link=0;
        wait(!dut.link_up);#1;
        check(!dut.core.audio_stream_rst_n && !dut.core.eth_stream_rst_n,
              "Link loss did not asynchronously reset both domains");
        check(dut.core.sample_fifo.wbin==0 && dut.core.sample_fifo.rbin==0,
              "FIFO pointers not cleared while audio clock stopped");
        check(dut.calibration_done,"Link loss destroyed completed calibration");
        repeat(10) @(negedge eth_clk);
        dut.phy.requested_link=1;
        wait(dut.core.eth_stream_rst_n);
        repeat(8) @(negedge eth_clk);
        check(!dut.core.audio_stream_rst_n,"Stopped audio clock released its stream reset");
        check(dut.core.stream_epoch==2,"Reconnection did not allocate next epoch");
        check(total_writes==128,"Link reconnect unexpectedly rewrote calibration");
        run_audio_clock=1;
        wait_active();
        check(dut.core.frontend.calibration.gain[0]==24'sd4000000 &&
              dut.core.frontend.calibration.offset[127]==32'sd12345,"Link reconnect changed coefficients");
        $display("[TB_DATA] Link-down with stopped audio clock resets both FIFO domains, independent release and epoch2 recovery PASS");

        // PLL loss is a global reset: boot coefficients must be loaded again.
        @(negedge audio_clk);dut.clocks.test_locked=0;
        #1;
        check(!dut.core.audio_rst_n && !dut.core.eth_rst_n && !phy_reset,
              "PLL loss did not assert board/core/PHY resets");
        repeat(10) @(negedge audio_clk);
        check(!dut.calibration_done && dut.cfg_channel==0,"Global reset did not restart calibration boot");
        dut.clocks.test_locked=1;
        wait_boot();wait_active();
        check(total_writes==256,"Global reset did not repeat exactly128 coefficient writes");
        check(dut.core.stream_epoch==1,"Global reset did not reset epoch counter");
        check(!dut.core.processing_error && !dut.core.overflow && !dut.core.framing_error,
              "Unexpected front-end/transport error during boot");
        $display("[TB_DATA] PLL unlock/relock reloads all coefficients and restarts epoch counter PASS");
        $display("[TB_DATA] boot_writes=%0d total_writes=%0d acquisitions=%0d checks=%0d",boot_writes,total_writes,starts,checks);
        $display("[TB_INFO] Simulation Finished!");
        $finish;
    end
    initial begin
        #100000;
        $fatal(1,"[TB_ERROR] Board boot global timeout");
    end
endmodule

// Physical models only. Clock frequencies are supplied by this testbench;
// real Pango PLL/DDR timing is verified by the separate vendor-IP simulation.
module pango_board_clocks(input wire ref_clk_27,ref_clk_125_p,ref_clk_125_n,rst_n,
    output wire audio_clk,eth_clk,locked);
    reg test_locked=0;
    assign audio_clk=ref_clk_27;
    assign eth_clk=ref_clk_125_p;
    assign locked=rst_n && test_locked;
endmodule
module rtl8211f_manager(input wire clk,rst_n,mdio_in,
    output wire phy_rst_n,mdc,mdio_out,mdio_oe,
    output reg ready=0,link_up=0,output wire fault,output wire [4:0] phy_address);
    reg requested_link=0;
    assign phy_rst_n=rst_n;
    assign mdc=0;assign mdio_out=1;assign mdio_oe=0;assign fault=0;assign phy_address=5;
    always @(posedge clk or negedge rst_n)
        if(!rst_n) begin ready<=0;link_up<=0;end
        else begin ready<=1;link_up<=requested_link;end
endmodule
module pango_rgmii_io(input wire tx_clk,rst_n,input wire [7:0] tx_data,
    input wire tx_en,tx_er,rgmii_rxc,rgmii_rx_ctl,input wire [3:0] rgmii_rxd,
    output wire rx_clk,output wire [7:0] rx_data,output wire rx_dv,rx_er,
    output wire rgmii_txc,rgmii_tx_ctl,output wire [3:0] rgmii_txd);
    assign rx_clk=rgmii_rxc;assign rx_data={rgmii_rxd,rgmii_rxd};
    assign rx_dv=rgmii_rx_ctl;assign rx_er=0;
    assign rgmii_txc=tx_clk;assign rgmii_tx_ctl=tx_en;assign rgmii_txd=tx_data[3:0];
endmodule
