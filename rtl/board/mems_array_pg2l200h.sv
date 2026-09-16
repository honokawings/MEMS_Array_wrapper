`timescale 1ns/1ps
// Pango MINI PG2L200H FBB676 board top. See fpga constraints and board guide.
module mems_array_pg2l200h(
    input wire sys_clk_27,sys_clk_125_p,sys_clk_125_n,reset_n,
    input wire [63:0] pdm_data,
    output wire [3:0] mic_clk,
    input wire PHY0_RXC,PHY0_RXCTRL,
    input wire [3:0] PHY0_RXD,
    output wire PHY0_TXC,PHY0_TXCTRL,
    output wire [3:0] PHY0_TXD,
    output wire PHY0_MDC,
    inout wire PHY0_MDIO,
    output wire RSTN_OUT
);
    wire audio_clk,eth_clk,locked;
    pango_board_clocks clocks(.ref_clk_27(sys_clk_27),.ref_clk_125_p(sys_clk_125_p),
        .ref_clk_125_n(sys_clk_125_n),.rst_n(reset_n),.audio_clk(audio_clk),.eth_clk(eth_clk),.locked(locked));
    wire common_arst_n=reset_n && locked;
    wire audio_rst_n,eth_rst_n;
    reset_release audio_reset(.clk(audio_clk),.arst_n(common_arst_n),.rst_n(audio_rst_n));
    reset_release eth_reset(.clk(eth_clk),.arst_n(common_arst_n),.rst_n(eth_rst_n));
    wire mdio_out,mdio_oe,phy_ready,link_up,phy_fault;
    assign PHY0_MDIO=mdio_oe ? mdio_out : 1'bz;
    rtl8211f_manager phy(.clk(eth_clk),.rst_n(eth_rst_n),.phy_rst_n(RSTN_OUT),
        .mdc(PHY0_MDC),.mdio_out(mdio_out),.mdio_oe(mdio_oe),.mdio_in(PHY0_MDIO),
        .ready(phy_ready),.link_up(link_up),.fault(phy_fault),.phy_address());
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
    reg signed [23:0] cfg_gain;
    reg signed [31:0] cfg_offset;
    wire cfg_ready;
    always @* begin
        cfg_gain=24'sd4194304;cfg_offset=0;
        case(cfg_channel)
            `include "calibration_coeff.svh"
            default: begin cfg_gain=24'sd4194304;cfg_offset=0;end
        endcase
    end
    always @(posedge audio_clk) begin
        if(!audio_rst_n) begin cfg_channel<=0;calibration_done<=0;end
        else if(!calibration_done && cfg_ready) begin
            if(cfg_channel==127) calibration_done<=1;
            else cfg_channel<=cfg_channel+1'b1;
        end
    end
    wire pdm_clock;
    mems_ethernet_core core(.audio_clk(audio_clk),.eth_clk(eth_clk),.rx_clk(rx_clk),.rst_n(common_arst_n),
        .run(calibration_done),.link_up(link_up),.pdm_data(pdm_data),.mic_clk(pdm_clock),
        .started(),.acquisition_active(),.cfg_valid(!calibration_done),.cfg_channel(cfg_channel),
        .cfg_gain(cfg_gain),.cfg_offset(cfg_offset),.cfg_ready(cfg_ready),
        .gmii_rxd(rx_data),.gmii_rx_dv(rx_dv),.gmii_rx_er(rx_er),.gmii_txd(tx_data),
        .gmii_tx_en(tx_en),.gmii_tx_er(tx_er),.overflow(),.processing_error(),.clipped(),
        .framing_error(),.tx_error(),.dropped_frames(),.stream_epoch(),.tx_packet_done());
    assign mic_clk={4{pdm_clock}};
endmodule
