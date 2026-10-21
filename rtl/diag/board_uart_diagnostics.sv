`timescale 1ns/1ps
// Independent 27 MHz supervisory domain. No payload or control bus is sampled
// by independent per-bit synchronizers: local-domain snapshots use handshakes.
module board_uart_diagnostics #(
    parameter integer UART_DIV=234,REPORT_CYCLES=6750000,MS_CYCLES=27000,
    RESET_CYCLES=540000,MODE_KEY_CYCLES=2700000,WINDOW_CYCLES=270000,PRESCALE_BITS=10
)(
    input wire ref_clk,raw125_clk,clk96,audio_clk,eth_clk,rx_clk,
    input wire uart_rx,physical_reset_n,input wire [2:0] pll_lock,
    input wire common_arst_n,audio_rst_n,eth_rst_n,input wire [4:0] controller_led,
    input wire [127:0] audio_status,rx_status,input wire [575:0] eth_status,
    input wire [255:0] i2s_status,input wire audio_gain_cfg_ready,
    output wire audio_i2s_enable,output wire [6:0] audio_i2s_channel,
    output wire [23:0] audio_even_gain,audio_odd_gain,output wire audio_gain_cfg_valid,
    output wire uart_tx,system_reset_n,mode_key_n
);
    wire [7:0] startup;
    board_diag_reg #(.WIDTH(8)) boot(.clk(ref_clk),.d({startup[6:0],1'b1}),.q(startup));
    wire observer_rst_n=startup[7];
    wire [7:0] rx_data;
    wire rx_valid,rx_error;
    diag_uart_rx #(.CLKS_PER_BIT(UART_DIV)) receiver(.clk(ref_clk),.rst_n(observer_rst_n),
        .rx(uart_rx),.data(rx_data),.valid(rx_valid),.error(rx_error));
    wire legacy_valid;
    wire cmd_reset=legacy_valid && rx_data==8'h72;
    wire cmd_clear=legacy_valid && rx_data==8'h63;
    wire cmd_toggle=legacy_valid && rx_data==8'h74;
    wire cmd_status=legacy_valid && (rx_data==8'h73 || rx_data==8'h68);
    wire command=cmd_reset|cmd_clear|cmd_toggle|cmd_status;
    reg [31:0] reset_count,mode_count;
    reg [3:0] clear_count;
    reg [15:0] command_count,rx_error_count,unknown_count;
    reg [7:0] last_command;
    assign system_reset_n=physical_reset_n && observer_rst_n && reset_count==0;
    assign mode_key_n=mode_count==0;
    always @(posedge ref_clk) begin
        if(!observer_rst_n)begin
            reset_count<=RESET_CYCLES;mode_count<=0;clear_count<=0;
            command_count<=0;rx_error_count<=0;unknown_count<=0;last_command<=0;
        end else begin
            if(cmd_reset)reset_count<=RESET_CYCLES;
            else if(reset_count!=0)reset_count<=reset_count-1'b1;
            if(cmd_reset || !physical_reset_n)mode_count<=0;
            else if(cmd_toggle)mode_count<=MODE_KEY_CYCLES;
            else if(mode_count!=0)mode_count<=mode_count-1'b1;
            if(cmd_clear)clear_count<=15;else if(clear_count!=0)clear_count<=clear_count-1'b1;
            if(command)begin command_count<=command_count+1'b1;last_command<=rx_data;end
            if(rx_error)rx_error_count<=rx_error_count+1'b1;
            if(legacy_valid && !command && rx_data!=8'h0d && rx_data!=8'h0a)unknown_count<=unknown_count+1'b1;
        end
    end
    wire [63:0] gray,deltas;
    board_diag_counter #(.PRESCALE_BITS(PRESCALE_BITS)) count_raw(.clk(raw125_clk),.gray(gray[15:0]));
    board_diag_counter #(.PRESCALE_BITS(PRESCALE_BITS)) count_96(.clk(clk96),.gray(gray[31:16]));
    board_diag_counter #(.PRESCALE_BITS(PRESCALE_BITS)) count_audio(.clk(audio_clk),.gray(gray[47:32]));
    board_diag_counter #(.PRESCALE_BITS(PRESCALE_BITS)) count_eth(.clk(eth_clk),.gray(gray[63:48]));
    wire [3:0] good,fault,seen,now_fault;
    wire [10:0] sampled;
    board_clock_observer #(.WINDOW_CYCLES(WINDOW_CYCLES),.PRESCALE_BITS(PRESCALE_BITS)) observer(
        .ref_clk(ref_clk),.key_n({clear_count==0,clear_count==0,1'b1,1'b1,system_reset_n}),
        .pll_lock(pll_lock),.common_arst_n(common_arst_n),.audio_rst_n(audio_rst_n),.eth_rst_n(eth_rst_n),
        .controller_led(audio_rst_n?controller_led:5'b0),.clocks_gray(gray),.led(),.frequency_good(good),
        .sticky_fault(fault),.measured_deltas(deltas),.sampled_status(sampled),.ever_healthy(seen),.live_fault(now_fault));
    wire launch;
    wire [127:0] audio_snapshot,rx_snapshot;
    wire [575:0] eth_snapshot;
    wire [2:0] fresh,busy;
    diag_snapshot_cdc #(.WIDTH(128)) audio_bridge(.dst_clk(ref_clk),.dst_rst_n(observer_rst_n),.launch(launch),
        .src_clk(audio_clk),.src_data(audio_status),.data(audio_snapshot),.valid(fresh[0]),.busy(busy[0]));
    diag_snapshot_cdc #(.WIDTH(576)) eth_bridge(.dst_clk(ref_clk),.dst_rst_n(observer_rst_n),.launch(launch),
        .src_clk(eth_clk),.src_data(eth_status),.data(eth_snapshot),.valid(fresh[1]),.busy(busy[1]));
    diag_snapshot_cdc #(.WIDTH(128)) rx_bridge(.dst_clk(ref_clk),.dst_rst_n(observer_rst_n),.launch(launch),
        .src_clk(rx_clk),.src_data(rx_status),.data(rx_snapshot),.valid(fresh[2]),.busy(busy[2]));
    wire [1023:0] words;
    assign words[31:0]={4'b0,!system_reset_n,seen,now_fault,fault,good,sampled}; // word2
    assign words[63:32]=deltas[31:0]; // word3 raw125 low,96 high
    assign words[95:64]=deltas[63:32]; // word4 audio low,eth high
    assign words[127:96]={8'b0,last_command,command_count};
    assign words[159:128]={unknown_count,rx_error_count};
    assign words[191:160]={24'b0,1'b0,busy,1'b0,fresh};
    assign words[319:192]=audio_snapshot;
    assign words[895:320]=eth_snapshot; // PHY9 words then network9 words
    assign words[1023:896]=rx_snapshot;
    wire desired_enable,config_pending,audio_reset_released;
    wire [6:0] desired_channel;
    wire [23:0] desired_even_gain,desired_odd_gain;
    wire audio_launch,audio_fresh,audio_busy;
    wire [255:0] control_snapshot;
    wire [7:0] aux_data;
    wire aux_valid,aux_last,aux_ready;
    audio_config_cdc configuration(.ref_clk(ref_clk),.ref_rst_n(observer_rst_n),.audio_clk(audio_clk),.audio_rst_n(audio_rst_n),
        .desired_enable(desired_enable),.desired_channel(desired_channel),.desired_even_gain(desired_even_gain),.desired_odd_gain(desired_odd_gain),
        .pending(config_pending),.audio_reset_released(audio_reset_released),.audio_i2s_enable(audio_i2s_enable),
        .audio_i2s_channel(audio_i2s_channel),.audio_even_gain(audio_even_gain),.audio_odd_gain(audio_odd_gain),
        .audio_gain_cfg_valid(audio_gain_cfg_valid),.audio_gain_cfg_ready(audio_gain_cfg_ready));
    diag_snapshot_cdc #(.WIDTH(256)) control_bridge(.dst_clk(ref_clk),.dst_rst_n(observer_rst_n),.launch(audio_launch),
        .src_clk(audio_clk),.src_data(i2s_status),.data(control_snapshot),.valid(audio_fresh),.busy(audio_busy));
    uart_audio_control control(.clk(ref_clk),.rst_n(observer_rst_n),.rx_data(rx_data),.rx_valid(rx_valid),.rx_error(rx_error),
        .legacy_valid(legacy_valid),.desired_enable(desired_enable),.desired_channel(desired_channel),
        .desired_even_gain(desired_even_gain),.desired_odd_gain(desired_odd_gain),.config_pending(config_pending),
        .audio_reset_released(audio_reset_released),.snapshot_launch(audio_launch),.snapshot_data(control_snapshot),.snapshot_fresh(audio_fresh),
        .tx_data(aux_data),.tx_valid(aux_valid),.tx_last(aux_last),.tx_ready(aux_ready));
    board_uart_report #(.UART_DIV(UART_DIV),.REPORT_CYCLES(REPORT_CYCLES),.MS_CYCLES(MS_CYCLES)) report(
        .clk(ref_clk),.rst_n(observer_rst_n),.request(command|rx_error),.status_words(words),
        .aux_data(aux_data),.aux_valid(aux_valid),.aux_last(aux_last),.aux_ready(aux_ready),.snapshot_launch(launch),.tx(uart_tx));
endmodule
