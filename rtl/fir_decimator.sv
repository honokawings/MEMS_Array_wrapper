`timescale 1ns/1ps
// Banked history RAM, one read + one write per lane per clock.
// Input vectors are written over GROUPS clocks while an independent MAC engine runs.
// DEPTH includes overwrite margin for samples arriving during a filter job.
module fir_decimator #(
    parameter integer CHANNELS = 128,
    parameter integer LANES = 16,
    parameter integer TAPS = 63,
    parameter integer DECIMATION = 4,
    parameter integer DEPTH = 128,
    parameter integer COEFF_SET = 1
) (
    input wire clk, rst_n,
    input wire [CHANNELS*32-1:0] data_i,
    input wire valid_i,
    output wire [CHANNELS*32-1:0] data_o,
    output reg valid_o,
    output reg overrun_o,
    output wire clip_o
);
    localparam integer GROUPS = CHANNELS/LANES;
    localparam integer GW = (GROUPS < 2) ? 1 : $clog2(GROUPS);
    localparam integer AW = $clog2(DEPTH);
    localparam integer TW = $clog2(TAPS+1);
    localparam integer DW = (DECIMATION < 2) ? 1 : $clog2(DECIMATION);
    reg [CHANNELS*32-1:0] input_hold;
    reg writing, busy;
    reg [GW-1:0] write_group, compute_group;
    reg [AW-1:0] write_pointer, base_pointer;
    reg [DW-1:0] decimation_phase;
    reg [TW-1:0] history_count, job_history, issue_count;
    reg read_valid, partial_valid, middle_valid, product_valid;
    reg read_last, partial_last, middle_last, product_last;
    reg final_valid;
    reg [GW-1:0] final_group;
    reg signed [31:0] read_coefficient;
    wire issue = busy && (issue_count < TAPS);
    wire [AW-1:0] read_pointer = base_pointer - issue_count;
    wire [LANES-1:0] lane_clip;
    assign clip_o = |lane_clip;

    function automatic signed [31:0] coefficient(input integer address);
        begin
            if(COEFF_SET==1) begin
                case(address)
`include "fir1_coeff.svh"
                    default: coefficient=0;
                endcase
            end else begin
                case(address)
`include "fir2_coeff.svh"
                    default: coefficient=0;
                endcase
            end
        end
    endfunction

    function automatic signed [71:0] rounded(input signed [71:0] value);
        reg signed [41:0] quotient, rounded_quotient;
        reg increment;
        begin
            // Arithmetic floor plus one implements nearest, ties away from 0:
            // positive ties increment; negative ties retain the floor.
            // This avoids a 72-bit abs/add/negate chain on the final MAC path.
            quotient=$signed(value[71:30]);
            increment=value[29] && (!value[71] || (|value[28:0]));
            rounded_quotient=quotient+(increment ? 42'sd1 : 42'sd0);
            rounded={{30{rounded_quotient[41]}},rounded_quotient};
        end
    endfunction

    always @(posedge clk) begin
        if(!rst_n) begin
            input_hold<=0; writing<=0; busy<=0;
            write_group<=0; compute_group<=0;
            write_pointer<=0; base_pointer<=0; decimation_phase<=0;
            history_count<=0; job_history<=0; issue_count<=0;
            read_valid<=0; partial_valid<=0; middle_valid<=0; product_valid<=0;
            read_last<=0; partial_last<=0; middle_last<=0; product_last<=0;
            final_valid<=0; final_group<=0;
            read_coefficient<=0; valid_o<=0; overrun_o<=0;
        end else begin
            valid_o<=0;
            read_valid<=issue;
            partial_valid<=read_valid; partial_last<=read_last;
            middle_valid<=partial_valid; middle_last<=partial_last;
            product_valid<=middle_valid; product_last<=middle_last;
            final_valid<=product_valid && product_last;
            if(product_valid && product_last) final_group<=compute_group;
            if(final_valid && final_group==GROUPS-1) valid_o<=1;
            if(issue) begin
                read_coefficient<=coefficient(issue_count);
                read_last<=(issue_count==TAPS-1);
                issue_count<=issue_count+1'b1;
            end
            if(product_valid && product_last) begin
                issue_count<=0;
                if(compute_group==GROUPS-1) busy<=0;
                else compute_group<=compute_group+1'b1;
            end
            if(valid_i) begin
                if(writing) overrun_o<=1;
                else begin
                    input_hold<=data_i; writing<=1; write_group<=0;
                    if(history_count<TAPS) history_count<=history_count+1'b1;
                end
            end
            if(writing) begin
                if(write_group==GROUPS-1) begin
                    writing<=0; write_pointer<=write_pointer+1'b1;
                    if(decimation_phase==DECIMATION-1) begin
                        decimation_phase<=0;
                        if(busy) overrun_o<=1;
                        else begin
                            busy<=1; compute_group<=0; issue_count<=0;
                            base_pointer<=write_pointer; job_history<=history_count;
                        end
                    end else decimation_phase<=decimation_phase+1'b1;
                end else write_group<=write_group+1'b1;
            end
        end
    end
    genvar l,g;
    generate for(l=0;l<LANES;l=l+1) begin: lane
        // No RAM reset: job_history masks uninitialised locations after restart.
        reg signed [31:0] history [0:GROUPS*DEPTH-1];
        reg signed [31:0] read_sample;
        reg [31:0] product_ll;
        reg signed [32:0] product_lh, product_hl;
        reg signed [31:0] product_hh, high_product;
        reg [15:0] low_product;
        reg signed [33:0] middle_product;
        reg signed [63:0] product;
        reg signed [71:0] accumulator, final_sum;
        wire signed [71:0] sum = accumulator + {{8{product[63]}},product};
        wire signed [71:0] rounded_sum = rounded(final_sum);
        // a*b = ll + ((lh+hl)<<16) + (hh<<32).  Carry-save compression
        // adds the three middle operands with only one 34-bit carry chain.
        wire [33:0] middle_a = {product_lh[32],product_lh};
        wire [33:0] middle_b = {product_hl[32],product_hl};
        wire [33:0] middle_c = {18'b0,product_ll[31:16]};
        wire [33:0] middle_bits = middle_a ^ middle_b ^ middle_c;
        wire [33:0] middle_carry = ((middle_a & middle_b) | (middle_a & middle_c) | (middle_b & middle_c)) << 1;
        wire signed [31:0] upper_product = high_product + {{14{middle_product[33]}},middle_product[33:16]};
        reg [GROUPS*32-1:0] result;
        reg clipped;
        assign lane_clip[l]=clipped;
        // Synchronous simple-dual-port RAM template.
        always @(posedge clk) begin
            if(rst_n && writing)
                history[write_group*DEPTH+write_pointer] <= input_hold[(write_group*LANES+l)*32 +: 32];
            if(issue) begin
                if(issue_count<job_history) read_sample<=history[compute_group*DEPTH+read_pointer];
                else read_sample<=0;
            end
        end
        always @(posedge clk) begin
            if(!rst_n) begin
                product_ll<=0; product_lh<=0; product_hl<=0; product_hh<=0;
                high_product<=0; low_product<=0; middle_product<=0;
                product<=0; accumulator<=0; final_sum<=0; result<=0; clipped<=0;
            end else begin
                // Each multiplier fits one 18x18 hardware multiplier.  In
                // particular, low halves are positive 17-bit signed operands.
                if(read_valid) begin
                    product_ll<=read_sample[15:0]*read_coefficient[15:0];
                    product_lh<=$signed({1'b0,read_sample[15:0]})*$signed(read_coefficient[31:16]);
                    product_hl<=$signed(read_sample[31:16])*$signed({1'b0,read_coefficient[15:0]});
                    product_hh<=$signed(read_sample[31:16])*$signed(read_coefficient[31:16]);
                end
                if(partial_valid) begin
                    middle_product<=$signed(middle_bits)+$signed(middle_carry);
                    high_product<=product_hh; low_product<=product_ll[15:0];
                end
                if(middle_valid) product<={upper_product,middle_product[15:0],low_product};
                if(product_valid) begin
                    if(product_last) begin
                        accumulator<=0; final_sum<=sum;
                    end else accumulator<=sum;
                end
                if(final_valid) begin
                    if(rounded_sum > 72'sd2147483647) begin
                        result[final_group*32 +: 32]<=32'h7fffffff; clipped<=1;
                    end else if(rounded_sum < -72'sd2147483648) begin
                        result[final_group*32 +: 32]<=32'h80000000; clipped<=1;
                    end else result[final_group*32 +: 32]<=rounded_sum[31:0];
                end
            end
        end
        for(g=0;g<GROUPS;g=g+1) begin: flatten
            assign data_o[(g*LANES+l)*32 +: 32]=result[g*32 +: 32];
        end
    end endgenerate
    // synthesis translate_off
    initial begin
        if(CHANNELS<1 || CHANNELS%LANES || DEPTH<TAPS+8 || (DEPTH&(DEPTH-1)) ||
           DECIMATION<1 || !((COEFF_SET==1 && TAPS==63)||(COEFF_SET==2 && TAPS==127)))
            $fatal(1,"Invalid FIR parameters");
    end
    // synthesis translate_on
endmodule
