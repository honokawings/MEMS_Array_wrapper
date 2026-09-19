`timescale 1ns/1ps
module clock_reset_diag #(
    parameter integer WINDOW_CYCLES=270000, PRESCALE_BITS=10,
    parameter integer REF_HEARTBEAT_CYCLES=13500000,
    parameter integer KEY_DEBOUNCE_CYCLES=2457600, AUDIO_HEARTBEAT_CYCLES=61440000
)(
    input wire sys_clk_27,sys_clk_125_p,sys_clk_125_n,
    input wire [4:0] key_n,
    output wire [4:0] led,
    output wire [3:0] mic_clk,
    output wire phy_reset_n
);
    wire ref_clk,raw125_clk,clk96,audio_clk,eth_clk,locked;
    wire [2:0] pll_lock;
    pango_clock_probe clocks(.ref_clk_27(sys_clk_27),.ref_clk_125_p(sys_clk_125_p),
        .ref_clk_125_n(sys_clk_125_n),.rst_n(key_n[0]),.audio_clk(audio_clk),.eth_clk(eth_clk),
        .locked(locked),.monitor_ref_clk(ref_clk),.monitor_raw125_clk(raw125_clk),
        .monitor_clk96(clk96),.monitor_locks(pll_lock));
    wire common_arst_n=key_n[0] && locked;
    wire audio_rst_n,eth_rst_n;
    // These are the unmodified production reset-release and key/LED modules.
    reset_release audio_reset(.clk(audio_clk),.arst_n(common_arst_n),.rst_n(audio_rst_n));
    reset_release eth_reset(.clk(eth_clk),.arst_n(common_arst_n),.rst_n(eth_rst_n));
    wire [4:0] controller_led;
    board_selftest_control #(.DEBOUNCE_CYCLES(KEY_DEBOUNCE_CYCLES),.HEARTBEAT_CYCLES(AUDIO_HEARTBEAT_CYCLES))
        original_control(.clk(audio_clk),.rst_n(audio_rst_n),.key_n(key_n[1]),
        .local_pass(1'b0),.local_fail(1'b0),.link_up(1'b0),.phy_fault(1'b0),.tx_pass(1'b0),.tx_fault(1'b0),
        .selftest_mode(),.led(controller_led));
    wire [63:0] clocks_gray;
    clock_diag_counter #(.PRESCALE_BITS(PRESCALE_BITS)) count_raw125(.clk(raw125_clk),.gray(clocks_gray[15:0]));
    clock_diag_counter #(.PRESCALE_BITS(PRESCALE_BITS)) count_96(.clk(clk96),.gray(clocks_gray[31:16]));
    clock_diag_counter #(.PRESCALE_BITS(PRESCALE_BITS)) count_audio(.clk(audio_clk),.gray(clocks_gray[47:32]));
    clock_diag_counter #(.PRESCALE_BITS(PRESCALE_BITS)) count_eth(.clk(eth_clk),.gray(clocks_gray[63:48]));
    clock_observer #(.WINDOW_CYCLES(WINDOW_CYCLES),.PRESCALE_BITS(PRESCALE_BITS),.HEARTBEAT_CYCLES(REF_HEARTBEAT_CYCLES))
        observer(.ref_clk(ref_clk),.key_n(key_n),.pll_lock(pll_lock),.common_arst_n(common_arst_n),
        .audio_rst_n(audio_rst_n),.eth_rst_n(eth_rst_n),.controller_led(controller_led),
        .clocks_gray(clocks_gray),.led(led),.frequency_good(),.sticky_fault(),.measured_deltas());
    assign mic_clk=4'b0;
    assign phy_reset_n=1'b0;
endmodule
