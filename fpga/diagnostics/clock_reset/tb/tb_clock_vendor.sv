`timescale 1ns/1fs
module tb_clock_vendor;
    reg ref27=0,ref125=0,grs_n=0;
    reg [4:0] key_n=5'b11110;
    always #(500.0/27.0) ref27=~ref27;
    always #4 ref125=~ref125;
    GTP_GRS GRS_INST(.GRS_N(grs_n));
    wire [4:0] led;
    wire [3:0] mic_clk;
    wire phy_reset_n;
    clock_reset_diag #(.WINDOW_CYCLES(2700),.PRESCALE_BITS(4),.REF_HEARTBEAT_CYCLES(16),
        .KEY_DEBOUNCE_CYCLES(16),.AUDIO_HEARTBEAT_CYCLES(64)) dut(
        .sys_clk_27(ref27),.sys_clk_125_p(ref125),.sys_clk_125_n(~ref125),
        .key_n(key_n),.led(led),.mic_clk(mic_clk),.phy_reset_n(phy_reset_n));
    integer checks=0,reference_edges=0,audio_edges=0,before_edges;
    always @(dut.observer.heartbeat) if(grs_n) reference_edges=reference_edges+1;
    always @(dut.controller_led[0]) if(grs_n) audio_edges=audio_edges+1;
    task check(input bit ok,input string message);
        begin checks=checks+1;if(!ok)$fatal(1,"[TB_ERROR] %s at %t led=%b",message,$time,led);end
    endtask
    task settle; begin repeat(12) @(negedge ref27);end endtask
    task press(input [4:0] value);begin @(negedge ref27);key_n=value;settle();end endtask
    task verify_period(input integer channel,input real expected);
        realtime started,period_ns;
        begin
            case(channel)
                0:begin @(posedge dut.raw125_clk);started=$realtime;repeat(128)@(posedge dut.raw125_clk);end
                1:begin @(posedge dut.clk96);started=$realtime;repeat(128)@(posedge dut.clk96);end
                2:begin @(posedge dut.audio_clk);started=$realtime;repeat(128)@(posedge dut.audio_clk);end
                3:begin @(posedge dut.eth_clk);started=$realtime;repeat(128)@(posedge dut.eth_clk);end
            endcase
            period_ns=($realtime-started)/128.0;
            check(period_ns>expected*0.9999 && period_ns<expected*1.0001,"vendor generated period");
            $display("[TB_MONITOR] channel=%0d period_ns=%0.9f",channel,period_ns);
        end
    endtask
    initial begin
        #200;grs_n=1;settle();
        check(dut.locked===0,"initial KEY0 holds PLL reset");
        before_edges=reference_edges;repeat(64)@(negedge ref27);
        check(reference_edges-before_edges>=3,"reference heartbeat survives KEY0");
        press(5'b11111);
        wait(dut.audio_rst_n===1 && dut.eth_rst_n===1);settle();
        check(led[4:1]===4'b1111,"default PLL/reset page");
        verify_period(0,8.0);verify_period(1,1000.0/96.0);
        verify_period(2,1000.0/122.88);verify_period(3,8.0);
        #410000;
        check(dut.observer.frequency_good===4'b1111,"all four frequencies qualified");
        check(dut.observer.sticky_fault===0,"clean startup has no false history");
        press(5'b11101);check(led[4:1]===4'b1111,"KEY1 frequency page");
        press(5'b11011);check(led[4:1]===4'b1110,"KEY2 reset page released");
        before_edges=reference_edges;
        press(5'b11010);repeat(64)@(negedge ref27);
        check(led[4:1]===4'b0001,"KEY0 asserts three resets while KEY2 held");
        check(reference_edges-before_edges>=3,"reference heartbeat persists during PLL reset");
        check(dut.observer.sticky_fault===0,"intentional reset is not a fault");
        press(5'b11011);wait(dut.audio_rst_n===1 && dut.eth_rst_n===1);settle();
        check(led[4:1]===4'b1110,"local resets release after KEY0");
        #410000;
        check(dut.observer.frequency_good===4'b1111,"frequency requalifies after reset");
        check(dut.observer.sticky_fault===0,"reset/relock leaves history clean");
        press(5'b10111);check(led[1]===0,"original mode starts off");
        before_edges=audio_edges;repeat(64)@(negedge ref27);
        check(audio_edges-before_edges>=3,"original audio heartbeat runs");
        press(5'b10101);check(led[1]===1,"KEY3 plus KEY1 toggles original mode");
        repeat(64)@(negedge ref27);check(led[1]===1,"long press does not retrigger");
        press(5'b10111);press(5'b10101);check(led[1]===0,"second KEY1 press returns mode");
        press(5'b01111);check(led[4:1]===0,"history page clean");
        press(5'b00111);check(led[4:1]===0,"clear chord priority");
        check(mic_clk===0 && phy_reset_n===0,"unused interfaces held inactive");
        $display("[TB_INFO] Simulation Finished! checks=%0d",checks);$finish;
    end
    initial begin #2000000;$fatal(1,"[TB_ERROR] vendor test timeout");end
endmodule
