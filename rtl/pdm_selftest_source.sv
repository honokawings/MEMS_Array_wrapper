`timescale 1ns/1ps
// Deterministic 1024-period stimulus: unique channel DC plus a 3 kHz square
// component with four phase groups. Bit-reversed thresholds distribute PDM
// pulses. The real capture synchronizers and both LR slots remain in the path.
module pdm_selftest_source(
    input wire clk,rst_n,enable,mic_clk,
    output wire [63:0] pdm_data
);
    reg mic_previous;
    reg [9:0] period_index;
    reg [127:0] channel_bits;
    wire [7:0] reversed_index={period_index[0],period_index[1],period_index[2],period_index[3],
                              period_index[4],period_index[5],period_index[6],period_index[7]};
    integer c;
    reg [1:0] phase_group;
    reg [7:0] threshold;
    always @(posedge clk) begin
        if(!rst_n || !enable) begin
            mic_previous<=0;period_index<=0;channel_bits<=0;
        end else begin
            mic_previous<=mic_clk;
            if(mic_clk && !mic_previous) begin
                for(c=0;c<128;c=c+1) begin
                    phase_group=period_index[9:8]+(c%4);
                    threshold=64+c+(phase_group[1] ? 16 : -16);
                    channel_bits[c]<=reversed_index<threshold;
                end
                period_index<=period_index+1'b1;
            end
        end
    end
    genvar k;
    generate for(k=0;k<64;k=k+1) begin: slots
        assign pdm_data[k]=mic_clk ? channel_bits[2*k+1] : channel_bits[2*k];
    end endgenerate
endmodule
