`timescale 1ns/1ps
// Portable complete front end and Ethernet MAC. All external GMII clocks are
// 125 MHz; audio_clk is exactly 122.88 MHz. Configuration/run use audio_clk.
// Link loss flushes both sides of the sample FIFO and starts a new stream epoch.
module mems_ethernet_core #(
    parameter integer STARTUP_CYCLES=153600,
    parameter integer SETTLE_FRAMES=96,
    parameter integer DC_ESTIMATE_LOG2=0,
    parameter integer ARP_RETRY_CYCLES=125000000,
    parameter integer SELFTEST_FRAMES=48000,
    parameter integer SELFTEST_TIMEOUT=12288000,
    parameter integer SELFTEST_TX_PACKETS=16000,
    parameter integer INDEPENDENT_AUDIO=0,
    parameter [47:0] LOCAL_MAC=48'h020000000128,
    parameter [31:0] LOCAL_IP=32'hc0a80a02,
    parameter [31:0] PEER_IP=32'hc0a80a01,
    parameter [15:0] LOCAL_PORT=5000,PEER_PORT=5000
) (
    input wire audio_clk,eth_clk,rx_clk,rst_n,
    input wire run,link_up,selftest_mode,
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
    output wire tx_packet_done,
    output wire selftest_pass,selftest_fail,
    output reg selftest_tx_pass,selftest_tx_fail,
    output wire [127:0] debug_audio,output wire [287:0] debug_eth,
    output wire [127:0] debug_rx,
    input tri0 parity_cfg_valid,
    input wire [23:0] parity_even_gain,parity_odd_gain,
    output wire parity_cfg_ready,
    output wire monitor_pcm_valid,
    output wire [6:0] monitor_pcm_channel,
    output wire signed [23:0] monitor_pcm_data,
    output wire [23:0] parity_active_even_gain,parity_active_odd_gain
);
    wire audio_rst_n,eth_rst_n,audio_stream_rst_n,eth_stream_rst_n;
    reset_release audio_reset(.clk(audio_clk),.arst_n(rst_n),.rst_n(audio_rst_n));
    reset_release eth_reset(.clk(eth_clk),.arst_n(rst_n),.rst_n(eth_rst_n));
    // Both FIFO domains see the same asynchronous reset condition. Neither can
    // resume with pointers from the old stream even if one clock has stopped.
    wire peer_ready;
    // ARP is independent of this stream. The common asynchronous assertion
    // flushes both FIFO domains; each reset_release synchronizes deassertion
    // locally, including the Ethernet-domain peer_ready indication.
    wire stream_arst_n=rst_n && run && link_up && peer_ready;
    reset_release audio_stream_reset(.clk(audio_clk),.arst_n(stream_arst_n),.rst_n(audio_stream_rst_n));
    reset_release eth_stream_reset(.clk(eth_clk),.arst_n(stream_arst_n),.rst_n(eth_stream_rst_n));
    assign acquisition_active=audio_stream_rst_n;
    // Board listening continues without Ethernet; portable default preserves
    // the original network-gated stream and built-in oracle startup behavior.
    wire frontend_enable=INDEPENDENT_AUDIO && !selftest_mode ? (audio_rst_n && run) : audio_stream_rst_n;
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
    wire dc_ready;
    wire [127:0] dc_rejected;
    reg [31:0] debug_pcm_samples,debug_pcm_frame;
    always @(posedge audio_clk or negedge audio_rst_n) begin
        if(!audio_rst_n)begin debug_pcm_samples<=0;debug_pcm_frame<=0;end
        else if(pcm_valid && pcm_ready) begin
            debug_pcm_samples<=debug_pcm_samples+1'b1;debug_pcm_frame<=pcm_frame_id[31:0];
        end
    end
    assign debug_audio={debug_pcm_frame,debug_pcm_samples,dropped_frames,
        {17'b0,((DC_ESTIMATE_LOG2!=0) && (|dc_rejected)),
         ((DC_ESTIMATE_LOG2!=0) && dc_ready),(DC_ESTIMATE_LOG2!=0),
         3'b0,
         selftest_fail,selftest_pass,clipped,processing_error,overflow,selftest_mode,
         run,acquisition_active,started}};
    wire [255:0] debug_network;
    // Net flags [11:0] are from MAC; [12:15] add packetizer/BIST/stream state.
    assign debug_eth={debug_network[255:192],stream_epoch,debug_network[191:32],
        {16'b0,eth_stream_rst_n,selftest_tx_fail,selftest_tx_pass,framing_error,debug_network[11:0]}};
    wire frontend_cfg_ready;
    wire frontend_parity_cfg_ready;
    wire [63:0] synthetic_pdm;
    wire selftest_active=selftest_mode && audio_stream_rst_n;
    pdm_selftest_source stimulus(.clk(audio_clk),.rst_n(audio_rst_n),.enable(selftest_active),
        .mic_clk(mic_clk),.pdm_data(synthetic_pdm));
    pcm_selftest_checker #(.FIRST_FRAME(SETTLE_FRAMES),.PASS_FRAMES(SELFTEST_FRAMES),
        .TIMEOUT_CYCLES(SELFTEST_TIMEOUT)) selftest_checker(
        .clk(audio_clk),.rst_n(audio_rst_n),.enable(selftest_active),.pcm_data(pcm_data),
        .pcm_channel(pcm_channel),.pcm_frame_id(pcm_frame_id),.pcm_valid(pcm_valid),.pcm_ready(pcm_ready),
        .pcm_first(pcm_first),.pcm_last(pcm_last),.pipeline_error(overflow|processing_error|clipped),
        .passed(selftest_pass),.failed(selftest_fail),.checked_frames(),.first_bad_frame(),.first_bad_channel());
    // Mode is held throughout a stream; board mode changes first hold run low
    // for the complete 128-write calibration reload. Faults are sticky levels.
    (* syn_preserve=1 *) reg [1:0] test_meta,test_sync;
    reg [31:0] test_tx_count,test_tx_idle;
    always @(posedge eth_clk) begin
        if(!eth_rst_n) begin test_meta<=0;test_sync<=0;end
        else begin test_meta<={selftest_fail,selftest_mode};test_sync<=test_meta;end
        // MAC clears UDP errors while the stream is disabled. Arm BIST only
        // after a complete resumed stream cycle has reached that domain.
        if(!eth_stream_rst_n || !was_streaming || !test_sync[0]) begin
            test_tx_count<=0;test_tx_idle<=0;selftest_tx_pass<=0;selftest_tx_fail<=0;
        end else begin
            if(tx_packet_done) begin
                test_tx_idle<=0;
                if(test_tx_count<SELFTEST_TX_PACKETS) test_tx_count<=test_tx_count+1'b1;
                if(test_tx_count>=SELFTEST_TX_PACKETS-1) selftest_tx_pass<=1;
            end else if(test_tx_idle<125000000) test_tx_idle<=test_tx_idle+1'b1;
            if(tx_error || framing_error || test_tx_idle==125000000) begin
                selftest_tx_fail<=1;selftest_tx_pass<=0;
            end
            if(selftest_tx_fail) selftest_tx_pass<=0;
        end
    end
    // The board and core have independent reset release synchronizers. Do not
    // acknowledge boot writes until this core can actually retain coefficients.
    assign cfg_ready=audio_rst_n && frontend_cfg_ready;
    assign parity_cfg_ready=audio_rst_n && frontend_parity_cfg_ready;
    mems_array_top #(.STARTUP_CYCLES(STARTUP_CYCLES),.SETTLE_FRAMES(SETTLE_FRAMES),
        .DC_ESTIMATE_LOG2(DC_ESTIMATE_LOG2)) frontend(
        .clk(audio_clk),.rst_n(audio_rst_n),.enable(frontend_enable),
        .pdm_data(selftest_mode ? synthetic_pdm : pdm_data),
        .mic_clk(mic_clk),.started(started),.cfg_valid(cfg_valid),.cfg_channel(cfg_channel),
        .cfg_gain(cfg_gain),.cfg_offset(cfg_offset),.cfg_ready(frontend_cfg_ready),.pcm_data(pcm_data),
        .pcm_channel(pcm_channel),.pcm_frame_id(pcm_frame_id),.pcm_valid(pcm_valid),
        .pcm_first(pcm_first),.pcm_last(pcm_last),.pcm_ready(pcm_ready),
        .overflow(overflow),.dropped_frames(dropped_frames),.processing_error(processing_error),.clipped(clipped),
        .parity_cfg_valid(parity_cfg_valid),.parity_even_gain(parity_even_gain),.parity_odd_gain(parity_odd_gain),
        .parity_cfg_ready(frontend_parity_cfg_ready),.parity_bypass(selftest_mode),
        .parity_active_even_gain(parity_active_even_gain),.parity_active_odd_gain(parity_active_odd_gain),
        .dc_ready(dc_ready),.dc_rejected(dc_rejected));
    wire [99:0] sample_word;
    wire sample_valid,sample_ready;
    // Elastic output register separates the wide frame-RAM read/multiplexer
    // from the asynchronous FIFO's RAM write setup path. Sample metadata and
    // status travel with the data and stay stable for any downstream stall.
    reg [99:0] audio_sample;
    reg audio_sample_valid;
    wire audio_sample_ready;
    reg network_frame_started;
    assign pcm_ready=audio_stream_rst_n ? (!audio_sample_valid || audio_sample_ready) : frontend_enable;
    assign monitor_pcm_valid=pcm_valid && pcm_ready;
    assign monitor_pcm_channel=pcm_channel;
    assign monitor_pcm_data=pcm_data;
    always @(posedge audio_clk or negedge audio_stream_rst_n) begin
        if(!audio_stream_rst_n) begin
            audio_sample<=0;
            audio_sample_valid<=0;
            network_frame_started<=0;
        end else if(pcm_ready) begin
            if(pcm_valid && pcm_first) network_frame_started<=1;
            audio_sample_valid<=pcm_valid && (network_frame_started || pcm_first);
            if(pcm_valid && (network_frame_started || pcm_first))
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
        .selftest_mode(test_sync[0]),.selftest_error(test_sync[1]),
        .sample_data(sample_word[23:0]),.sample_channel(sample_word[32:26]),
        .sample_frame_id(sample_word[96:33]),.sample_first(sample_word[25]),.sample_last(sample_word[24]),
        .sample_status(sample_word[99:97]),.sample_valid(sample_valid),.sample_ready(sample_ready),
        .payload_data(payload_data),.payload_valid(payload_valid),.payload_ready(payload_ready),
        .payload_last(payload_last),.payload_length(payload_length),.framing_error(framing_error),.packet_accepted());
    ethernet_udp_engine #(.LOCAL_MAC(LOCAL_MAC),.LOCAL_IP(LOCAL_IP),.PEER_IP(PEER_IP),
        .LOCAL_PORT(LOCAL_PORT),.PEER_PORT(PEER_PORT),.ARP_RETRY_CYCLES(ARP_RETRY_CYCLES)) network(
        .clk(eth_clk),.rst_n(eth_rst_n),.link_up(link_up),
        .stream_enable(eth_stream_rst_n),.peer_ready(peer_ready),.rx_clk(rx_clk),
        .tx_payload_data(payload_data),.tx_payload_valid(payload_valid),.tx_payload_ready(payload_ready),
        .tx_payload_last(payload_last),.tx_payload_length(payload_length),
        .tx_packet_done(tx_packet_done),.tx_error(tx_error),.gmii_rxd(gmii_rxd),
        .gmii_rx_dv(gmii_rx_dv),.gmii_rx_er(gmii_rx_er),.gmii_txd(gmii_txd),
        .gmii_tx_en(gmii_tx_en),.gmii_tx_er(gmii_tx_er),.debug_status(debug_network),.debug_rx(debug_rx));
endmodule
