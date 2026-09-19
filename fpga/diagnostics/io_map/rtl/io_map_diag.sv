`timescale 1ns/1ps
// Diagnostic A: pin-to-pin inversion, with no clock, reset or state.
// Active-low KEY0..4 illuminate active-high LED0..4. Contact bounce is visible.
module io_map_direct(
    input wire [4:0] key_n,
    output wire [4:0] led,
    output wire [3:0] mic_clk,
    output wire phy_reset_n
);
    assign led = ~key_n;
    assign mic_clk = 4'b0000;
    assign phy_reset_n = 1'b0;
endmodule

// Diagnostic B: 27 MHz direct oscillator, no PLL and no button-controlled reset.
// 10-second repeating signature: ALL, OFF, ALL, OFF, L0, L1, L2, L3, L4, OFF.
// A pressed key overrides the pattern combinationally, even with clock stopped.
// Explicit vendor FF INIT values use configuration GRS, not an inferred initial.
module io_map_walk #(
    parameter integer STEP_CYCLES = 27000000
)(
    input wire sys_clk_27,
    input wire [4:0] key_n,
    output wire [4:0] led,
    output wire [3:0] mic_clk,
    output wire phy_reset_n
);
    localparam integer TICK_W = $clog2(STEP_CYCLES) < 1 ? 1 : $clog2(STEP_CYCLES);
    wire ref_in, clk;
    GTP_INBUF #(.IOSTANDARD("LVCMOS33")) u_ref(.I(sys_clk_27), .O(ref_in));
    GTP_CLKBUFG u_clk(.CLKIN(ref_in), .CLKOUT(clk));
    wire [TICK_W-1:0] tick_count, next_tick;
    wire [3:0] phase, next_phase;
    wire step = tick_count >= STEP_CYCLES-1;
    assign next_tick = step ? {TICK_W{1'b0}} : tick_count + 1'b1;
    assign next_phase = step ? (phase >= 9 ? 4'd0 : phase + 1'b1) : phase;
    genvar i;
    generate
        for(i=0; i<TICK_W; i=i+1) begin: g_tick
            GTP_DFF #(.INIT(1'b0), .GRS_EN("TRUE")) u_ff(
                .CLK(clk), .D(next_tick[i]), .Q(tick_count[i]));
        end
        for(i=0; i<4; i=i+1) begin: g_phase
            GTP_DFF #(.INIT(1'b0), .GRS_EN("TRUE")) u_ff(
                .CLK(clk), .D(next_phase[i]), .Q(phase[i]));
        end
    endgenerate
    reg [4:0] pattern;
    always @* begin
        case(phase)
            0,2: pattern=5'b11111;
            4: pattern=5'b00001;
            5: pattern=5'b00010;
            6: pattern=5'b00100;
            7: pattern=5'b01000;
            8: pattern=5'b10000;
            default: pattern=5'b00000;
        endcase
    end
    assign led = (key_n != 5'b11111) ? ~key_n : pattern;
    assign mic_clk = 4'b0000;
    assign phy_reset_n = 1'b0;
endmodule
