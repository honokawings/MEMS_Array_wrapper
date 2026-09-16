`timescale 1ns/1ps
// Portable complete front end and Ethernet MAC. All external GMII clocks are
// 125 MHz; audio_clk is exactly 122.88 MHz. Configuration/run use audio_clk.
// Link loss flushes both sides of the sample FIFO and starts a new stream epoch.
module mems_ethernet_core #(
    parameter integer STARTUP_CYCLES=153600,
    parameter integer SETTLE_FRAMES=96,
    parameter integer ARP_RETRY_CYCLES=125000000,
    parameter [47:0] LOCAL_MAC=48'h020000000128,
    parameter [31:0] LOCAL_IP=32'hc0a80a02,
    parameter [31:0] PEER_IP=32'hc0a80a01,
    parameter [15:0] LOCAL_PORT=5000,PEER_PORT=5000
) (
    input wire audio_clk,eth_clk,rx_clk,rst_n,
    input wire run,link_up,
    input wire [63:0] pdm_data,
    output wire mic_clk,started,acquisition_active,
    input wire cfg_valid,
    input wire [6:0] cfg_channel,
    input wire signed [23:0] cfg_gain,
    input wire signed [31:0] cfg_offset,
    output wire cfg_ready,
    input wire [7:0] gmii_rxd,
    input wire gmii_rx_dv,gmii_rx_er,
    output wire [7:0] gmii_txd,
    output wire gmii_tx_en,gmii_tx_er,
    output wire overflow,processing_error,clipped,framing_error,tx_error,
    output wire [31:0] dropped_frames,
    output reg [31:0] stream_epoch,
    output wire tx_packet_done
);
    wire audio_rst_n,eth_rst_n,audio_stream_rst_n,eth_stream_rst_n;
    reset_release audio_reset(.clk(audio_clk),.arst_n(rst_n),.rst_n(audio_rst_n));
    reset_release eth_reset(.clk(eth_clk),.arst_n(rst_n),.rst_n(eth_rst_n));
    // Both FIFO domains see the same asynchronous reset condition. Neither can
    // resume with pointers from the old stream even if one clock has stopped.
    wire stream_arst_n=rst_n && run && link_up;
    reset_release audio_stream_reset(.clk(audio_clk),.arst_n(stream_arst_n),.rst_n(audio_stream_rst_n));
    reset_release eth_stream_reset(.clk(eth_clk),.arst_n(stream_arst_n),.rst_n(eth_stream_rst_n));
    assign acquisition_active=audio_stream_rst_n;
    reg was_streaming;
    always @(posedge eth_clk) begin
        if(!eth_rst_n) begin was_streaming<=0;stream_epoch<=0;end
        else begin
            was_streaming<=eth_stream_rst_n;
            if(eth_stream_rst_n && !was_streaming) stream_epoch<=stream_epoch+1'b1;
        end
    end
    wire [23:0] pcm_data;
    wire [6:0] pcm_channel;
    wire [63:0] pcm_frame_id;
    wire pcm_valid,pcm_first,pcm_last,pcm_ready;
    wire frontend_cfg_ready;
    // The board and core have independent reset release synchronizers. Do not
    // acknowledge boot writes until this core can actually retain coefficients.
    assign cfg_ready=audio_rst_n && frontend_cfg_ready;
    mems_array_top #(.STARTUP_CYCLES(STARTUP_CYCLES),.SETTLE_FRAMES(SETTLE_FRAMES)) frontend(
        .clk(audio_clk),.rst_n(audio_rst_n),.enable(audio_stream_rst_n),.pdm_data(pdm_data),
        .mic_clk(mic_clk),.started(started),.cfg_valid(cfg_valid),.cfg_channel(cfg_channel),
        .cfg_gain(cfg_gain),.cfg_offset(cfg_offset),.cfg_ready(frontend_cfg_ready),.pcm_data(pcm_data),
        .pcm_channel(pcm_channel),.pcm_frame_id(pcm_frame_id),.pcm_valid(pcm_valid),
        .pcm_first(pcm_first),.pcm_last(pcm_last),.pcm_ready(pcm_ready),
        .overflow(overflow),.dropped_frames(dropped_frames),.processing_error(processing_error),.clipped(clipped));
    wire [99:0] sample_word;
    wire sample_valid,sample_ready;
    // Elastic output register separates the wide frame-RAM read/multiplexer
    // from the asynchronous FIFO's RAM write setup path. Sample metadata and
    // status travel with the data and stay stable for any downstream stall.
    reg [99:0] audio_sample;
    reg audio_sample_valid;
    wire audio_sample_ready;
    assign pcm_ready=audio_stream_rst_n && (!audio_sample_valid || audio_sample_ready);
    always @(posedge audio_clk or negedge audio_stream_rst_n) begin
        if(!audio_stream_rst_n) begin
            audio_sample<=0;
            audio_sample_valid<=0;
        end else if(pcm_ready) begin
            audio_sample_valid<=pcm_valid;
            if(pcm_valid)
                audio_sample<={processing_error,overflow,clipped,pcm_frame_id,pcm_channel,pcm_first,pcm_last,pcm_data};
        end
    end
    async_sample_fifo #(.WIDTH(100),.ADDRESS_BITS(10)) sample_fifo(
        .wr_clk(audio_clk),.wr_rst_n(audio_stream_rst_n),
        .wr_data(audio_sample),.wr_valid(audio_sample_valid),.wr_ready(audio_sample_ready),
        .rd_clk(eth_clk),.rd_rst_n(eth_stream_rst_n),
        .rd_data(sample_word),.rd_valid(sample_valid),.rd_ready(sample_ready));
    wire [7:0] payload_data;
    wire payload_valid,payload_ready,payload_last;
    wire [15:0] payload_length;
    pcm_udp_packetizer packetizer(
        .clk(eth_clk),.rst_n(eth_stream_rst_n),.stream_epoch(stream_epoch),
        .sample_data(sample_word[23:0]),.sample_channel(sample_word[32:26]),
        .sample_frame_id(sample_word[96:33]),.sample_first(sample_word[25]),.sample_last(sample_word[24]),
        .sample_status(sample_word[99:97]),.sample_valid(sample_valid),.sample_ready(sample_ready),
        .payload_data(payload_data),.payload_valid(payload_valid),.payload_ready(payload_ready),
        .payload_last(payload_last),.payload_length(payload_length),.framing_error(framing_error),.packet_accepted());
    ethernet_udp_engine #(.LOCAL_MAC(LOCAL_MAC),.LOCAL_IP(LOCAL_IP),.PEER_IP(PEER_IP),
        .LOCAL_PORT(LOCAL_PORT),.PEER_PORT(PEER_PORT),.ARP_RETRY_CYCLES(ARP_RETRY_CYCLES)) network(
        .clk(eth_clk),.rst_n(eth_rst_n),.link_up(eth_stream_rst_n),.rx_clk(rx_clk),
        .tx_payload_data(payload_data),.tx_payload_valid(payload_valid),.tx_payload_ready(payload_ready),
        .tx_payload_last(payload_last),.tx_payload_length(payload_length),
        .tx_packet_done(tx_packet_done),.tx_error(tx_error),.gmii_rxd(gmii_rxd),
        .gmii_rx_dv(gmii_rx_dv),.gmii_rx_er(gmii_rx_er),.gmii_txd(gmii_txd),
        .gmii_tx_en(gmii_tx_en),.gmii_tx_er(gmii_tx_er));
endmodule
