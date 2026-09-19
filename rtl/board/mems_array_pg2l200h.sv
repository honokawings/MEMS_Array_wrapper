`timescale 1ns/1ps
// Pango MINI PG2L200H FBB676 board top. See fpga constraints and board guide.
module mems_array_pg2l200h #(
    parameter integer KEY_DEBOUNCE_CYCLES=2457600,
    parameter integer SELFTEST_FRAMES=48000,
    parameter integer SELFTEST_TX_PACKETS=16000,
    parameter integer STARTUP_CYCLES=153600,
    parameter integer UART_ENABLE=1,
    parameter integer UART_DIV=234,UART_REPORT_CYCLES=6750000,UART_MS_CYCLES=27000,
    UART_RESET_CYCLES=540000,UART_MODE_CYCLES=2700000,UART_WINDOW_CYCLES=270000,
    UART_PRESCALE_BITS=10
)(
    input wire sys_clk_27,sys_clk_125_p,sys_clk_125_n,reset_n,
    input wire selftest_key_n,
    input wire uart_rx,output wire uart_tx,
    output wire [4:0] led,
    input wire [63:0] pdm_data,
    output wire [7:0] mic_clk,
    input wire PHY0_RXC,PHY0_RXCTRL,
    input wire [3:0] PHY0_RXD,
    output wire PHY0_TXC,PHY0_TXCTRL,
    output wire [3:0] PHY0_TXD,
    output wire PHY0_MDC,
    inout wire PHY0_MDIO,
    output wire RSTN_OUT
);
    wire audio_clk,eth_clk,locked;
    wire monitor_ref_clk,monitor_raw125_clk,monitor_clk96;
    wire [2:0] monitor_locks;
    wire system_reset_n,uart_mode_key_n;
    pango_board_clocks clocks(.ref_clk_27(sys_clk_27),.ref_clk_125_p(sys_clk_125_p),
        .ref_clk_125_n(sys_clk_125_n),.rst_n(system_reset_n),.audio_clk(audio_clk),.eth_clk(eth_clk),.locked(locked),
        .monitor_ref_clk(monitor_ref_clk),.monitor_raw125_clk(monitor_raw125_clk),
        .monitor_clk96(monitor_clk96),.monitor_locks(monitor_locks));
    wire common_arst_n=system_reset_n && locked;
    wire audio_rst_n,eth_rst_n;
    reset_release audio_reset(.clk(audio_clk),.arst_n(common_arst_n),.rst_n(audio_rst_n));
    reset_release eth_reset(.clk(eth_clk),.arst_n(common_arst_n),.rst_n(eth_rst_n));
    wire mdio_out,mdio_oe,phy_ready,link_up,phy_fault;
    wire [287:0] phy_debug,eth_debug;
    wire [127:0] audio_debug,rx_debug;
    assign PHY0_MDIO=mdio_oe ? mdio_out : 1'bz;
    rtl8211f_manager phy(.clk(eth_clk),.rst_n(eth_rst_n),.phy_rst_n(RSTN_OUT),
        .mdc(PHY0_MDC),.mdio_out(mdio_out),.mdio_oe(mdio_oe),.mdio_in(PHY0_MDIO),
        .ready(phy_ready),.link_up(link_up),.fault(phy_fault),.phy_address(),.debug_status(phy_debug));
    wire rx_clk,rx_dv,rx_er,tx_en,tx_er;
    wire [7:0] rx_data,tx_data;
    pango_rgmii_io rgmii(.tx_clk(eth_clk),.rst_n(eth_rst_n),
        .rgmii_rxc(PHY0_RXC),.rgmii_rx_ctl(PHY0_RXCTRL),.rgmii_rxd(PHY0_RXD),
        .tx_data(tx_data),.tx_en(tx_en),.tx_er(tx_er),.rx_clk(rx_clk),.rx_data(rx_data),
        .rx_dv(rx_dv),.rx_er(rx_er),.rgmii_txc(PHY0_TXC),.rgmii_tx_ctl(PHY0_TXCTRL),.rgmii_txd(PHY0_TXD));
    // Configuration is applied once after reset, before acquisition can start.
    // Each channel retains its coefficients through link loss/reconnection.
    reg [6:0] cfg_channel;
    reg calibration_done;
    reg loaded_mode;
    wire selftest_mode,selftest_pass,selftest_fail,selftest_tx_pass,selftest_tx_fail;
    wire acquisition_run=calibration_done && loaded_mode==selftest_mode;
    board_selftest_control #(.DEBOUNCE_CYCLES(KEY_DEBOUNCE_CYCLES)) selftest_control(
        .clk(audio_clk),.rst_n(audio_rst_n),.key_n(selftest_key_n && uart_mode_key_n),.local_pass(selftest_pass),
        .local_fail(selftest_fail),.link_up(link_up),.phy_fault(phy_fault),
        .tx_pass(selftest_tx_pass),.tx_fault(selftest_tx_fail),.selftest_mode(selftest_mode),.led(led));
    reg signed [23:0] cfg_gain;
    reg signed [31:0] cfg_offset;
    wire cfg_ready;
    always @* begin
        cfg_gain=24'sd4194304;cfg_offset=0;
        case(cfg_channel)
            `include "calibration_coeff.svh"
            default: begin cfg_gain=24'sd4194304;cfg_offset=0;end
        endcase
        // Built-in oracle is independent of installed acoustic calibration.
        // Leaving test mode reloads the user's original ROM for every channel.
        if(selftest_mode) begin cfg_gain=24'sd4194304;cfg_offset=0;end
    end
    always @(posedge audio_clk) begin
        if(!audio_rst_n) begin cfg_channel<=0;calibration_done<=0;loaded_mode<=0;end
        else if(loaded_mode!=selftest_mode) begin
            cfg_channel<=0;calibration_done<=0;loaded_mode<=selftest_mode;
        end
        else if(!calibration_done && cfg_ready) begin
            if(cfg_channel==127) calibration_done<=1;
            else cfg_channel<=cfg_channel+1'b1;
        end
    end
    wire pdm_clock;
    mems_ethernet_core #(.STARTUP_CYCLES(STARTUP_CYCLES),.SELFTEST_FRAMES(SELFTEST_FRAMES),
        .SELFTEST_TX_PACKETS(SELFTEST_TX_PACKETS)) core(
        .audio_clk(audio_clk),.eth_clk(eth_clk),.rx_clk(rx_clk),.rst_n(common_arst_n),
        .run(acquisition_run),.link_up(link_up),.selftest_mode(selftest_mode),.pdm_data(pdm_data),.mic_clk(pdm_clock),
        .started(),.acquisition_active(),.cfg_valid(!calibration_done && loaded_mode==selftest_mode),.cfg_channel(cfg_channel),
        .cfg_gain(cfg_gain),.cfg_offset(cfg_offset),.cfg_ready(cfg_ready),
        .gmii_rxd(rx_data),.gmii_rx_dv(rx_dv),.gmii_rx_er(rx_er),.gmii_txd(tx_data),
        .gmii_tx_en(tx_en),.gmii_tx_er(tx_er),.overflow(),.processing_error(),.clipped(),
        .framing_error(),.tx_error(),.dropped_frames(),.stream_epoch(),.tx_packet_done(),
        .selftest_pass(selftest_pass),.selftest_fail(selftest_fail),
        .selftest_tx_pass(selftest_tx_pass),.selftest_tx_fail(selftest_tx_fail),
        .debug_audio(audio_debug),.debug_eth(eth_debug),.debug_rx(rx_debug));
    wire [127:0] board_audio_debug={audio_debug[127:32],
        8'b0,led,7'b0,loaded_mode,calibration_done,audio_rst_n,audio_debug[8:0]};
    generate if(UART_ENABLE)begin:g_uart
        board_uart_diagnostics #(.UART_DIV(UART_DIV),.REPORT_CYCLES(UART_REPORT_CYCLES),
            .MS_CYCLES(UART_MS_CYCLES),.RESET_CYCLES(UART_RESET_CYCLES),.MODE_KEY_CYCLES(UART_MODE_CYCLES),
            .WINDOW_CYCLES(UART_WINDOW_CYCLES),.PRESCALE_BITS(UART_PRESCALE_BITS)) diagnostics(
            .ref_clk(monitor_ref_clk),.raw125_clk(monitor_raw125_clk),.clk96(monitor_clk96),
            .audio_clk(audio_clk),.eth_clk(eth_clk),.rx_clk(rx_clk),.uart_rx(uart_rx),
            .physical_reset_n(reset_n),.pll_lock(monitor_locks),.common_arst_n(common_arst_n),
            .audio_rst_n(audio_rst_n),.eth_rst_n(eth_rst_n),.controller_led(led),
            .audio_status(audio_rst_n?board_audio_debug:128'b0),.rx_status(rx_debug),
            .eth_status(eth_rst_n?{eth_debug,phy_debug}:576'b0),
            .uart_tx(uart_tx),.system_reset_n(system_reset_n),.mode_key_n(uart_mode_key_n));
    end else begin:g_no_uart
        assign system_reset_n=reset_n;
        assign uart_mode_key_n=1'b1;
        assign uart_tx=1'b1;
    end endgenerate
    // Eight J10 clock pads share the exact same divider, phase and reset.
    // Drive strength and 1.8 V electrical standard are board FDC attributes.
    assign mic_clk={8{pdm_clock}};
endmodule
