`timescale 1ns/1ps
// Isolate the actual lane arithmetic with forced read-port operands.  Compare
// the three-stage partial-product pipeline to SV's independent signed multiply.
module tb_fir_arithmetic;
    reg clk=0,rst_n=0;
    always #4 clk=~clk;
    wire [31:0] data_o;
    wire valid_o,overrun_o,clip_o;
    fir_decimator #(.CHANNELS(1),.LANES(1)) dut(
        .clk(clk),.rst_n(rst_n),.data_i(32'b0),.valid_i(1'b0),
        .data_o(data_o),.valid_o(valid_o),.overrun_o(overrun_o),.clip_o(clip_o));
    reg signed [31:0] operand_a=0,operand_b=0;
    reg launch=0;
    reg signed [63:0] expected[0:22000];
    integer produced=0,checked=0,rounded_checked=0;
    reg [31:0] edges[0:11];
    reg [31:0] random_state=32'h1268a7c9;
    reg [31:0] random_operand;
    integer i,j;
    reg signed [71:0] rounding_input;
    function automatic [31:0] next_random(input [31:0] old);
        reg [31:0] x;
        begin x=old^(old<<13);x=x^(x>>17);next_random=x^(x<<5);end
    endfunction
    task automatic send_product(input signed [31:0] a,input signed [31:0] b);
        begin
            @(negedge clk);operand_a=a;operand_b=b;launch=1;
            expected[produced]=$signed(a)*$signed(b);produced=produced+1;
        end
    endtask
    task automatic check_round(input signed [71:0] value);
        reg signed [71:0] original,actual;
        begin
            if(value<0) original=-(((-value)+(72'sd1<<29))>>>30);
            else original=(value+(72'sd1<<29))>>>30;
            actual=dut.rounded(value);
            if(actual!==original) $fatal(1,"[TB_ERROR] rounding value=%h got=%h expected=%h",value,actual,original);
            rounded_checked=rounded_checked+1;
        end
    endtask
    always @(posedge clk) begin
        #1;
        if(rst_n && dut.product_valid) begin
            if(checked>=produced || dut.lane[0].product!==expected[checked])
                $fatal(1,"[TB_ERROR] product index=%0d got=%h expected=%h",checked,dut.lane[0].product,expected[checked]);
            checked=checked+1;
        end
    end
    initial begin
        edges[0]=0;edges[1]=1;edges[2]='1;edges[3]=32'h7fff;
        edges[4]=32'h8000;edges[5]=32'hffff;edges[6]=32'h10000;
        edges[7]=32'h7fff0000;edges[8]=32'h80000000;edges[9]=32'h7fffffff;
        edges[10]=32'hffff0000;edges[11]=32'hffff8000;
        force dut.lane[0].read_sample=operand_a;
        force dut.read_coefficient=operand_b;
        force dut.read_valid=launch;
        repeat(5) @(negedge clk);rst_n=1;
        for(i=0;i<12;i=i+1) for(j=0;j<12;j=j+1) send_product(edges[i],edges[j]);
        for(i=0;i<20000;i=i+1) begin
            random_state=next_random(random_state);random_operand=random_state;
            random_state=next_random(random_state);
            send_product(random_operand,random_state);
            rounding_input=$signed({operand_a,operand_b});check_round(rounding_input);
            if(i%13==0) begin @(negedge clk);launch=0;end
        end
        // +/- half-LSB and +/-32-bit output saturation boundary neighborhoods.
        for(i=-4;i<=4;i=i+1) begin
            rounding_input=(72'sd1<<29)+i;check_round(rounding_input);check_round(-rounding_input);
            rounding_input=(72'sd2147483647<<30)+(72'sd1<<29)+i;
            check_round(rounding_input);check_round(-rounding_input);
            rounding_input=(72'sd2147483648<<30)+(72'sd1<<29)+i;
            check_round(rounding_input);check_round(-rounding_input);
        end
        @(negedge clk);launch=0;
        repeat(10) @(negedge clk);
        if(checked!=produced) $fatal(1,"[TB_ERROR] pipeline lost products %0d/%0d",checked,produced);
        $display("[TB_INFO] FIR arithmetic PASS signed_products=%0d round_values=%0d",checked,rounded_checked);
        $display("[TB_INFO] Simulation Finished!");$finish;
    end
    initial begin #1000000;$fatal(1,"[TB_ERROR] watchdog");end
endmodule
