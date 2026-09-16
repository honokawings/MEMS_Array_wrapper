`timescale 1ns/1ps
// Portable 128-channel IM72D128V01 front end. Clock input: exactly 122.88 MHz.
// All control inputs are synchronous to clk. Reset must be held >= 2 clk cycles.
module mems_array_top #(
    parameter integer STARTUP_CYCLES=153600,
    parameter integer SETTLE_FRAMES=96,
    parameter integer FIFO_DEPTH=4
) (
    input wire clk, rst_n, enable,
    input wire [63:0] pdm_data,
    output wire mic_clk,
    output wire started,
    input wire cfg_valid,
    input wire [6:0] cfg_channel,
    input wire signed [23:0] cfg_gain,
    input wire signed [31:0] cfg_offset,
    output wire cfg_ready,
    output wire signed [23:0] pcm_data,
    output wire [6:0] pcm_channel,
    output wire [63:0] pcm_frame_id,
    output wire pcm_valid, pcm_first, pcm_last,
    input wire pcm_ready,
    output wire overflow,
    output wire [31:0] dropped_frames,
    output wire processing_error,
    output wire clipped
);
    wire pipeline_rst_n=rst_n && enable;
    wire [127:0] bits;
    wire bits_valid,cic_valid,fir1_valid,fir2_valid,cal_valid;
    wire [4095:0] cic_data,fir1_data,fir2_data;
    wire [3071:0] cal_data;
    wire cic_error,fir1_error,fir2_error,cal_error;
    wire fir1_clip,fir2_clip,cal_clip;
    reg [63:0] sample_index;
    pdm_capture #(.STARTUP_CYCLES(STARTUP_CYCLES)) capture(.clk(clk),.rst_n(rst_n),.enable(enable),.pdm_data(pdm_data),
        .mic_clk(mic_clk),.bits_o(bits),.valid_o(bits_valid),.started_o(started));
    cic_decimator cic(.clk(clk),.rst_n(pipeline_rst_n),.bits_i(bits),.valid_i(bits_valid),
        .data_o(cic_data),.valid_o(cic_valid),.overrun_o(cic_error));
    fir_decimator fir1(.clk(clk),.rst_n(pipeline_rst_n),.data_i(cic_data),.valid_i(cic_valid),
        .data_o(fir1_data),.valid_o(fir1_valid),.overrun_o(fir1_error),.clip_o(fir1_clip));
    fir_decimator #(.TAPS(127),.DECIMATION(2),.DEPTH(256),.COEFF_SET(2)) fir2(
        .clk(clk),.rst_n(pipeline_rst_n),.data_i(fir1_data),.valid_i(fir1_valid),
        .data_o(fir2_data),.valid_o(fir2_valid),.overrun_o(fir2_error),.clip_o(fir2_clip));
    pcm_calibration calibration(.clk(clk),.rst_n(rst_n),.enable(enable),
        .data_i(fir2_data),.valid_i(fir2_valid),.cfg_valid(cfg_valid),.cfg_channel(cfg_channel),
        .cfg_gain(cfg_gain),.cfg_offset(cfg_offset),.cfg_ready(cfg_ready),
        .data_o(cal_data),.valid_o(cal_valid),.clip_o(cal_clip),.overrun_o(cal_error));
    always @(posedge clk) begin
        if(!pipeline_rst_n) sample_index<=0;
        else if(cal_valid) sample_index<=sample_index+1'b1;
    end
    pcm_frame_fifo #(.DEPTH(FIFO_DEPTH)) output_fifo(.clk(clk),.rst_n(pipeline_rst_n),
        .frame_i(cal_data),.frame_id_i(sample_index),.valid_i(cal_valid && sample_index>=SETTLE_FRAMES),
        .pcm_data(pcm_data),.pcm_channel(pcm_channel),.pcm_frame_id(pcm_frame_id),
        .pcm_valid(pcm_valid),.pcm_first(pcm_first),.pcm_last(pcm_last),.pcm_ready(pcm_ready),
        .overflow_o(overflow),.dropped_frames_o(dropped_frames));
    assign processing_error=cic_error|fir1_error|fir2_error|cal_error;
    assign clipped=fir1_clip|fir2_clip|cal_clip;
endmodule
