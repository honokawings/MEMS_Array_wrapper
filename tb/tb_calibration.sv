`timescale 1ns/1ps
module tb_calibration;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,enable=0,valid_i=0,cfg_valid=0;
    reg [4095:0] data_i=0;
    reg [6:0] cfg_channel=0;
    reg signed [23:0] cfg_gain=0;
    reg signed [31:0] cfg_offset=0;
    wire cfg_ready,valid_o,clip_o,overrun_o;
    wire [3071:0] data_o;
    pcm_calibration dut(.*);
    integer c,k,seed=32'h51c02829,round_checks=0;
    reg signed [56:0] probe;
    reg signed [31:0] x[0:127],o[0:127];
    reg signed [23:0] g[0:127];
    longint signed p,y;
    task check_round(input reg signed [56:0] value);
        longint signed reference_product,reference_round;
        begin
            probe=value;
            force dut.product=probe;
            #1;
            reference_product=value;
            reference_round=(reference_product<0) ?
                -((-reference_product+268435456)>>>29) :
                  ((reference_product+268435456)>>>29);
            if($signed(dut.rounded_product)!==reference_round)
                $fatal(1,"[TB_ERROR] Calibration rounding product=%0d got=%0d expected=%0d",
                    value,$signed(dut.rounded_product),reference_round);
            round_checks=round_checks+1;
            release dut.product;
        end
    endtask
    initial begin
        // Independent magnitude-based oracle checks the actual RTL arithmetic,
        // including full-width products and both sides of half-LSB boundaries.
        check_round(57'sh100000000000000);
        check_round(57'sh0ffffffffffffff);
        for(k=-4;k<=4;k=k+1) begin
            check_round((longint'(k)<<29)-1);
            check_round(longint'(k)<<29);
            check_round((longint'(k)<<29)+1);
            check_round((longint'(k)<<29)+268435455);
            check_round((longint'(k)<<29)+268435456);
            check_round((longint'(k)<<29)+268435457);
        end
        for(k=0;k<20000;k=k+1) check_round({$urandom(seed),$urandom(seed)});
        $display("[TB_DATA] Calibration rounding checks=%0d",round_checks);
        repeat(3) @(negedge clk);rst_n=1;
        for(c=0;c<128;c=c+1) begin
            case(c%8)
                0: begin x[c]=64;o[c]=0;g[c]=4194304;end
                1: begin x[c]=-64;o[c]=0;g[c]=4194304;end
                2: begin x[c]=32'h7fffffff;o[c]=32'h80000000;g[c]=24'h7fffff;end
                3: begin x[c]=32'h80000000;o[c]=32'h7fffffff;g[c]=24'h7fffff;end
                4: begin x[c]=1234567;o[c]=-765432;g[c]=-4194304;end
                5: begin x[c]=-321;o[c]=123;g[c]=0;end
                6: begin x[c]=-65;o[c]=0;g[c]=4194304;end
                7: begin x[c]=63;o[c]=0;g[c]=4194304;end
            endcase
            @(negedge clk);cfg_valid=1;cfg_channel=c;cfg_gain=g[c];cfg_offset=o[c];
            data_i[c*32 +: 32]=x[c];
        end
        @(negedge clk);cfg_valid=0;enable=1;
        @(negedge clk);valid_i=1;
        @(negedge clk);valid_i=0;
        repeat(5) @(negedge clk);valid_i=1;
        @(negedge clk);valid_i=0;
        wait(valid_o);@(negedge clk);
        for(c=0;c<128;c=c+1) begin
            p=(longint'(x[c])-longint'(o[c]))*longint'(g[c]);
            y=(p<0)?-((-p+268435456)>>>29):((p+268435456)>>>29);
            if(y>8388607)y=8388607;
            if(y< -8388608)y=-8388608;
            if($signed(data_o[c*24 +: 24])!==y)
                $fatal(1,"[TB_ERROR] Calibration ch=%0d got=%0d expected=%0d",c,$signed(data_o[c*24 +: 24]),y);
        end
        if(!clip_o || !overrun_o) $fatal(1,"[TB_ERROR] Calibration flags");
        $display("[TB_DATA] 128 calibration cases: ties, extrema, negative/zero gain, clipping, overrun passed");
        $display("[TB_INFO] Simulation Finished!");$finish;
    end
    initial begin #100_000;$fatal(1,"[TB_ERROR] Calibration watchdog");end
endmodule
