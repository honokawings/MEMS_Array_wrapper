`timescale 1ns/1ps
// 122.88 MHz PCM monitor output for PCM5102 in standard I2S mode.
// 48 kHz stereo, 32-bit slots, 24 significant bits, selected mono duplicated.
// Inputs are synchronous to clk; pcm_valid is an accepted PCM transaction.
// A selection/enable request takes effect only at a left-frame boundary.
// Clock outputs remain continuous while muted; each missing sample is zero.
module pcm_i2s_tx (
    input wire clk, rst_n, enable,
    input wire [6:0] selected_channel,
    input wire pcm_valid,
    input wire [6:0] pcm_channel,
    input wire signed [23:0] pcm_data,
    output reg i2s_sck, i2s_bck, i2s_lrck, i2s_din,
    output reg [6:0] active_channel,
    output reg active_enable,
    output reg signed [23:0] last_pcm,
    output reg [31:0] received_samples, output_frames, underruns,
    output wire [31:0] verified_frames, serial_errors
);
    reg [2:0] sck_half;
    reg [4:0] bck_half;
    reg [5:0] slot_index;
    reg [31:0] shift_data;
    reg [6:0] observed_channel, cached_channel;
    reg observed_enable, cached_valid;
    reg signed [23:0] cached_pcm;
    wire request_changed = selected_channel != observed_channel || enable != observed_enable;
    wire incoming = enable && pcm_valid && pcm_channel == selected_channel;
    wire falling_bck = bck_half == 19 && i2s_bck;
    wire frame_boundary = falling_bck && slot_index == 0;
    wire use_cached = cached_valid && !request_changed && cached_channel == selected_channel;
    wire sample_available = incoming || use_cached;
    wire signed [23:0] next_frame_pcm = enable && sample_available ?
        (incoming ? pcm_data : cached_pcm) : 24'sd0;

    always @(posedge clk) begin
        if (!rst_n) begin
            sck_half <= 0; bck_half <= 0; slot_index <= 0;
            i2s_sck <= 0; i2s_bck <= 0; i2s_lrck <= 1; i2s_din <= 0;
            shift_data <= 0; active_channel <= 0; active_enable <= 0; last_pcm <= 0;
            observed_channel <= 0; observed_enable <= 0;
            cached_channel <= 0; cached_valid <= 0; cached_pcm <= 0;
            received_samples <= 0; output_frames <= 0; underruns <= 0;
        end else begin
            observed_channel <= selected_channel;
            observed_enable <= enable;
            if (sck_half == 4) begin sck_half <= 0; i2s_sck <= !i2s_sck; end
            else sck_half <= sck_half + 1'b1;
            if (bck_half == 19) begin bck_half <= 0; i2s_bck <= !i2s_bck; end
            else bck_half <= bck_half + 1'b1;

            // Invalidate every request change, even A -> B -> A between frames.
            // A fresh transaction for the new request may replace it immediately.
            if (request_changed || !enable) cached_valid <= 0;
            if (incoming) begin
                cached_pcm <= pcm_data; cached_channel <= pcm_channel; cached_valid <= 1;
                received_samples <= received_samples + 1'b1;
            end
            if (falling_bck) begin
                slot_index <= slot_index + 1'b1;
                if (slot_index == 0) begin
                    i2s_lrck <= 0; i2s_din <= 0;
                    active_channel <= selected_channel; active_enable <= enable;
                    last_pcm <= next_frame_pcm; shift_data <= {next_frame_pcm,8'b0};
                    cached_valid <= 0; output_frames <= output_frames + 1'b1;
                    if (enable && !sample_available) underruns <= underruns + 1'b1;
                end else if (slot_index == 32) begin
                    i2s_lrck <= 1; i2s_din <= 0; shift_data <= {last_pcm,8'b0};
                end else begin
                    i2s_din <= shift_data[31]; shift_data <= {shift_data[30:0],1'b0};
                end
            end
        end
    end

    // A separate receiver checks the actual registered serial signals, including
    // the one-BCK delay. It cannot certify PCB wiring or the DAC analog output.
    pcm_i2s_serial_monitor monitor(
        .clk(clk),.rst_n(rst_n),.bck(i2s_bck),.lrck(i2s_lrck),.din(i2s_din),
        .expected_pcm(last_pcm),.verified_frames(verified_frames),.serial_errors(serial_errors));
endmodule

module pcm_i2s_serial_monitor (
    input wire clk, rst_n, bck, lrck, din,
    input wire signed [23:0] expected_pcm,
    output reg [31:0] verified_frames, serial_errors
);
    reg previous_bck, previous_lrck, synchronized;
    reg [5:0] bit_index;
    reg [23:0] decoded, expected;
    reg left_bad, right_checked;
    wire [23:0] completed_word = {decoded[22:0],din};
    always @(posedge clk) begin
        if (!rst_n) begin
            previous_bck <= 0; previous_lrck <= 1; synchronized <= 0; bit_index <= 0;
            decoded <= 0; expected <= 0; left_bad <= 0; right_checked <= 0;
            verified_frames <= 0; serial_errors <= 0;
        end else begin
            previous_bck <= bck;
            if (bck && !previous_bck) begin
                previous_lrck <= lrck;
                if (lrck != previous_lrck) begin
                    bit_index <= 1; decoded <= 0;
                    if (!lrck) begin
                        synchronized <= 1; expected <= expected_pcm;
                        left_bad <= din != 0; right_checked <= 0;
                    end else if (synchronized && din != 0) left_bad <= 1;
                end else if (synchronized) begin
                    bit_index <= bit_index + 1'b1;
                    if (bit_index >= 1 && bit_index <= 24) begin
                        decoded <= completed_word;
                        if (bit_index == 24) begin
                            if (!lrck) left_bad <= left_bad || completed_word != expected;
                            else right_checked <= completed_word == expected;
                        end
                    end else if (bit_index >= 25 && bit_index <= 31) begin
                        if (din != 0) left_bad <= 1;
                        if (lrck && bit_index == 31) begin
                            verified_frames <= verified_frames + 1'b1;
                            if (left_bad || !right_checked || din != 0)
                                serial_errors <= serial_errors + 1'b1;
                        end
                    end
                end
            end
        end
    end
endmodule
