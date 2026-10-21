`timescale 1ns/1ps
// Bundled-data request/ACK. Desired registers live in the supervisor; an audio
// reset clears both handshake ends and causes automatic replay of those values.
module audio_config_cdc(
    input wire ref_clk,ref_rst_n,audio_clk,audio_rst_n,
    input wire desired_enable,input wire [6:0] desired_channel,
    input wire [23:0] desired_even_gain,desired_odd_gain,
    output wire pending,output wire audio_reset_released,
    output reg audio_i2s_enable,output reg [6:0] audio_i2s_channel,
    output reg [23:0] audio_even_gain,audio_odd_gain,
    output reg audio_gain_cfg_valid,input wire audio_gain_cfg_ready
);
    wire [55:0] desired={desired_enable,desired_channel,desired_even_gain,desired_odd_gain};
    wire bridge_rst_n=ref_rst_n && audio_rst_n;
    (* syn_preserve=1 *) reg [55:0] held,accepted;
    reg request_toggle,waiting,dirty;
    (* async_reg="true",syn_preserve=1 *) reg alive_meta,alive_sync,ack_meta,ack_sync;
    (* async_reg="true",syn_preserve=1 *) reg request_meta,request_sync;
    reg acknowledge;
    assign audio_reset_released=alive_sync;
    assign pending=!alive_sync || waiting || dirty || accepted!=desired;
    always @(posedge ref_clk or negedge bridge_rst_n) begin
        if(!bridge_rst_n)begin alive_meta<=0;alive_sync<=0;end
        else begin alive_meta<=1;alive_sync<=alive_meta;end
    end
    always @(posedge ref_clk or negedge bridge_rst_n) begin
        if(!bridge_rst_n)begin
            held<=0;accepted<=0;request_toggle<=0;waiting<=0;dirty<=1;ack_meta<=0;ack_sync<=0;
        end else begin
            ack_meta<=acknowledge;ack_sync<=ack_meta;
            if(!alive_sync)begin request_toggle<=0;waiting<=0;dirty<=1;end
            else if(waiting)begin
                if(ack_sync==request_toggle)begin waiting<=0;accepted<=held;dirty<=0;end
            end else if(dirty || accepted!=desired)begin
                held<=desired;request_toggle<=~request_toggle;waiting<=1;
            end
        end
    end
    always @(posedge audio_clk or negedge bridge_rst_n) begin
        if(!bridge_rst_n)begin
            request_meta<=0;request_sync<=0;acknowledge<=0;audio_gain_cfg_valid<=0;
            audio_i2s_enable<=1;audio_i2s_channel<=0;
            audio_even_gain<=24'h400000;audio_odd_gain<=24'h400000;
        end else begin
            request_meta<=request_toggle;request_sync<=request_meta;
            if(!audio_gain_cfg_valid && request_sync!=acknowledge)begin
                audio_even_gain<=held[47:24];audio_odd_gain<=held[23:0];audio_gain_cfg_valid<=1;
            end else if(audio_gain_cfg_valid && audio_gain_cfg_ready)begin
                audio_i2s_enable<=held[55];audio_i2s_channel<=held[54:48];
                audio_gain_cfg_valid<=0;acknowledge<=request_sync;
            end
        end
    end
endmodule
