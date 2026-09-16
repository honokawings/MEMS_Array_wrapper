`timescale 1ns/1ps
module tb_capture;
    reg clk=0;always #4.0690104167 clk=~clk;
    reg rst_n=0,enable=0;
    tri [1:0] pdm_data;
    reg [1:0] hi='z,lo='z;
    assign pdm_data=hi;assign pdm_data=lo;
    wire mic_clk,valid_o,started_o;
    wire [3:0] bits_o;
    pdm_capture #(.PAIRS(2)) dut(.*);
    integer periods=0,seen=0,cycle=0,last_valid_cycle=0;
    realtime last_edge=0,delta;
    always @(posedge mic_clk) begin
        periods=periods+1;lo<=#30 'z;hi<=#100 2'b10;
    end
    always @(negedge mic_clk) begin hi<=#30 'z;lo<=#100 2'b01;end
    always @(mic_clk) if(enable && rst_n) begin
        if(last_edge!=0) begin
            delta=$realtime-last_edge;
            if(delta<162.74 || delta>162.78) $fatal(1,"[TB_ERROR] PDM half-period %0f",delta);
        end
        last_edge=$realtime;
    end
    always @(posedge clk) if(rst_n && enable) begin
        cycle=cycle+1;
        if(valid_o) begin
            if(periods<153601 || !started_o || bits_o!==4'b1001)
                $fatal(1,"[TB_ERROR] Startup/LR mapping periods=%0d bits=%b",periods,bits_o);
            if(seen==0 && periods!=153601) $fatal(1,"[TB_ERROR] Startup is not exactly 153600 periods");
            if(seen!=0 && cycle-last_valid_cycle!=40) $fatal(1,"[TB_ERROR] Capture cadence");
            last_valid_cycle=cycle;
            seen=seen+1;
        end else if(periods<153601 && started_o) $fatal(1,"[TB_ERROR] Early startup");
    end
    initial begin
        repeat(4) @(negedge clk);rst_n=1;enable=1;
        wait(seen==4);@(negedge clk);enable=0;
        repeat(4) @(negedge clk);
        if(mic_clk || started_o || valid_o) $fatal(1,"[TB_ERROR] Capture disable");
        $display("[TB_DATA] Production 153600-period startup, 100ns DATA delay, LR mapping, clock duty passed");
        $display("[TB_INFO] Simulation Finished!");$finish;
    end
    initial begin #51_000_000;$fatal(1,"[TB_ERROR] Capture watchdog");end
endmodule
