`timescale 1ns/1ps
module uart_clock_diag #(
    parameter integer UART_DIV=234, WINDOW_CYCLES=270000, PRESCALE_BITS=10,
    REPORT_CYCLES=6750000, MS_CYCLES=27000, RESET_CYCLES=540000,
    MODE_KEY_CYCLES=2700000, KEY_DEBOUNCE_CYCLES=2457600, AUDIO_HEARTBEAT_CYCLES=61440000
)(
    input wire sys_clk_27,sys_clk_125_p,sys_clk_125_n,uart_rx,
    output wire uart_tx,output wire [3:0] mic_clk,output wire phy_reset_n
);
    wire ref_clk,raw125_clk,clk96,audio_clk,eth_clk,locked;
    wire [2:0] pll_lock;
    wire [7:0] startup_pipe;
    clock_diag_reg #(.WIDTH(8)) init_ff(.clk(ref_clk),.d({startup_pipe[6:0],1'b1}),.q(startup_pipe));
    wire observer_rst_n=startup_pipe[7];
    wire [7:0] rx_data;
    wire rx_valid,rx_error;
    diag_uart_rx #(.CLKS_PER_BIT(UART_DIV)) receiver(.clk(ref_clk),.rst_n(observer_rst_n),
        .rx(uart_rx),.data(rx_data),.valid(rx_valid),.error(rx_error));
    wire cmd_reset=rx_valid && rx_data==8'h72; // r: 20 ms PLL reset, observer/UART remains alive.
    wire cmd_clear=rx_valid && rx_data==8'h63; // c: clear history.
    wire cmd_toggle=rx_valid && rx_data==8'h74; // t: emulate one debounced mode-key press.
    wire cmd_status=rx_valid && (rx_data==8'h73 || rx_data==8'h68); // s/h: report.
    wire command=cmd_reset|cmd_clear|cmd_toggle|cmd_status;
    reg [31:0] reset_count,mode_count;
    reg [3:0] clear_count;
    reg [4:0] request_settle;
    reg [15:0] command_count,rx_error_count;
    reg [7:0] last_command;
    wire probe_rst_n=observer_rst_n && reset_count==0;
    always @(posedge ref_clk) begin
        if(!observer_rst_n) begin
            reset_count<=RESET_CYCLES;mode_count<=0;clear_count<=0;request_settle<=0;
            command_count<=0;rx_error_count<=0;last_command<=0;
        end else begin
            if(cmd_reset)reset_count<=RESET_CYCLES;
            else if(reset_count!=0)reset_count<=reset_count-1'b1;
            if(cmd_reset)mode_count<=0;
            else if(cmd_toggle)mode_count<=MODE_KEY_CYCLES;
            else if(mode_count!=0)mode_count<=mode_count-1'b1;
            if(cmd_clear)clear_count<=15;
            else if(clear_count!=0)clear_count<=clear_count-1'b1;
            if(command)begin command_count<=command_count+1'b1;last_command<=rx_data;end
            if(rx_error)rx_error_count<=rx_error_count+1'b1;
            // Allow command counters and reset status synchronizers to settle
            // before the requested snapshot (16 reference clocks = 0.593 us).
            if(command || rx_error)request_settle<=16;
            else if(request_settle!=0)request_settle<=request_settle-1'b1;
        end
    end
    pango_clock_probe clocks(.ref_clk_27(sys_clk_27),.ref_clk_125_p(sys_clk_125_p),
        .ref_clk_125_n(sys_clk_125_n),.rst_n(probe_rst_n),.audio_clk(audio_clk),.eth_clk(eth_clk),
        .locked(locked),.monitor_ref_clk(ref_clk),.monitor_raw125_clk(raw125_clk),
        .monitor_clk96(clk96),.monitor_locks(pll_lock));
    wire common_arst_n=probe_rst_n && locked;
    wire audio_rst_n,eth_rst_n;
    reset_release audio_reset(.clk(audio_clk),.arst_n(common_arst_n),.rst_n(audio_rst_n));
    reset_release eth_reset(.clk(eth_clk),.arst_n(common_arst_n),.rst_n(eth_rst_n));
    wire [4:0] controller_led;
    board_selftest_control #(.DEBOUNCE_CYCLES(KEY_DEBOUNCE_CYCLES),.HEARTBEAT_CYCLES(AUDIO_HEARTBEAT_CYCLES))
        original_control(.clk(audio_clk),.rst_n(audio_rst_n),.key_n(mode_count==0),
        .local_pass(1'b0),.local_fail(1'b0),.link_up(1'b0),.phy_fault(1'b0),.tx_pass(1'b0),.tx_fault(1'b0),
        .selftest_mode(),.led(controller_led));
    wire [63:0] clocks_gray,deltas;
    clock_diag_counter #(.PRESCALE_BITS(PRESCALE_BITS)) count_raw125(.clk(raw125_clk),.gray(clocks_gray[15:0]));
    clock_diag_counter #(.PRESCALE_BITS(PRESCALE_BITS)) count_96(.clk(clk96),.gray(clocks_gray[31:16]));
    clock_diag_counter #(.PRESCALE_BITS(PRESCALE_BITS)) count_audio(.clk(audio_clk),.gray(clocks_gray[47:32]));
    clock_diag_counter #(.PRESCALE_BITS(PRESCALE_BITS)) count_eth(.clk(eth_clk),.gray(clocks_gray[63:48]));
    wire [3:0] good,fault,seen,live_fault;
    wire [10:0] sampled_status;
    // Virtual key levels preserve the already-tested qualification/history
    // behavior. No physical LED/page buttons are used in this design.
    wire [4:0] virtual_keys={clear_count==0,clear_count==0,1'b1,1'b1,probe_rst_n};
    clock_observer #(.WINDOW_CYCLES(WINDOW_CYCLES),.PRESCALE_BITS(PRESCALE_BITS)) observer(
        .ref_clk(ref_clk),.key_n(virtual_keys),.pll_lock(pll_lock),.common_arst_n(common_arst_n),
        .audio_rst_n(audio_rst_n),.eth_rst_n(eth_rst_n),.controller_led(audio_rst_n?controller_led:5'b0),
        .clocks_gray(clocks_gray),.led(),.frequency_good(good),.sticky_fault(fault),.measured_deltas(deltas),
        .sampled_status(sampled_status),.ever_healthy(seen),.live_fault(live_fault));
    uart_clock_report #(.UART_DIV(UART_DIV),.REPORT_CYCLES(REPORT_CYCLES),.MS_CYCLES(MS_CYCLES)) report(
        .clk(ref_clk),.rst_n(observer_rst_n),.request(request_settle==1),.sampled_status(sampled_status),
        .frequency_good(good),.deltas(deltas),.seen(seen),.fault(fault),.live_fault(live_fault),
        .reset_active(!probe_rst_n),.command_count(command_count),.last_command(last_command),
        .rx_error_count(rx_error_count),.tx(uart_tx));
    assign mic_clk=4'b0;
    assign phy_reset_n=1'b0;
endmodule
