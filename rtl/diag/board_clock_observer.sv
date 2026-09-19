`timescale 1ns/1ps
// Configuration-initialized state. KEY0 deliberately does not reset these FFs.
module board_diag_reg #(parameter integer WIDTH=1, parameter [WIDTH-1:0] INIT=0)(
    input wire clk,input wire [WIDTH-1:0] d,output wire [WIDTH-1:0] q);
    genvar i;
    generate for(i=0;i<WIDTH;i=i+1) begin:g_bit
        GTP_DFF #(.GRS_EN("TRUE"),.INIT(INIT[i])) u_ff(.CLK(clk),.D(d[i]),.Q(q[i]));
    end endgenerate
endmodule

// Registered Gray counter increments once per 2**PRESCALE_BITS source edges.
// It remains independent of PLL LOCK and of the system's local reset release.
module board_diag_counter #(parameter integer PRESCALE_BITS=10)(
    input wire clk,output wire [15:0] gray);
    wire [PRESCALE_BITS-1:0] prescale;
    wire [15:0] count,count_next;
    assign count_next=count+(&prescale);
    board_diag_reg #(.WIDTH(PRESCALE_BITS)) u_prescale(.clk(clk),.d(prescale+1'b1),.q(prescale));
    board_diag_reg #(.WIDTH(16)) u_count(.clk(clk),.d(count_next),.q(count));
    board_diag_reg #(.WIDTH(16)) u_gray(.clk(clk),.d((count_next>>1)^count_next),.q(gray));
endmodule

module board_diag_frequency #(
    parameter integer TARGET_HZ=125000000, WINDOW_CYCLES=270000, PRESCALE_BITS=10
)(input wire clk,window_tick,restart,input wire [15:0] gray_async,output wire good,
  output wire [15:0] last_delta);
    // Compare relative to the 27 MHz reference: +/-2%, plus 2 prescaled edges
    // for asynchronous endpoint/quantization effects. Arithmetic is 64-bit.
    localparam [63:0] NUM=64'd1*TARGET_HZ*WINDOW_CYCLES;
    localparam [63:0] DEN=64'd27000000*(64'd1<<PRESCALE_BITS);
    localparam [63:0] LOW=(NUM*98)/(DEN*100)>2 ? (NUM*98)/(DEN*100)-2 : 0;
    localparam [63:0] HIGH=(NUM*102+DEN*100-1)/(DEN*100)+2;
    (* syn_preserve=1 *) wire [15:0] meta,sync;
    wire [15:0] sample,previous,delta;
    wire have_previous,previous_candidate;
    wire candidate=have_previous && delta>=LOW && delta<=HIGH;
    board_diag_reg #(.WIDTH(16)) u_meta(.clk(clk),.d(gray_async),.q(meta));
    board_diag_reg #(.WIDTH(16)) u_sync(.clk(clk),.d(meta),.q(sync));
    function automatic [15:0] gray_to_binary(input [15:0] value);
        integer k;
        begin
            gray_to_binary[15]=value[15];
            for(k=14;k>=0;k=k-1) gray_to_binary[k]=gray_to_binary[k+1]^value[k];
        end
    endfunction
    assign sample=gray_to_binary(sync);
    assign delta=sample-previous; // Modulo subtraction handles counter wrap.
    board_diag_reg #(.WIDTH(16)) u_previous(.clk(clk),.d(window_tick?sample:previous),.q(previous));
    // KEY0 clears qualification, not the free-running source counters. This
    // prevents stale pre-reset GOOD from arming history during a partial window.
    board_diag_reg u_seen(.clk(clk),.d(restart?1'b0:(have_previous|window_tick)),.q(have_previous));
    board_diag_reg u_candidate(.clk(clk),.d(restart?1'b0:(window_tick?candidate:previous_candidate)),.q(previous_candidate));
    board_diag_reg u_good(.clk(clk),.d(restart?1'b0:(window_tick?(candidate&&previous_candidate):good)),.q(good));
    board_diag_reg #(.WIDTH(16)) u_delta(.clk(clk),.d(window_tick?delta:last_delta),.q(last_delta));
endmodule

module board_clock_observer #(
    parameter integer WINDOW_CYCLES=270000, PRESCALE_BITS=10, HEARTBEAT_CYCLES=13500000
)(
    input wire ref_clk,
    input wire [4:0] key_n,
    input wire [2:0] pll_lock, // [0]=96 MHz; [1]=audio; [2]=Ethernet PLL.
    input wire common_arst_n,audio_rst_n,eth_rst_n,
    input wire [4:0] controller_led,
    input wire [63:0] clocks_gray, // raw125,96,audio,eth in low-to-high slices.
    output wire [4:0] led,
    output wire [3:0] frequency_good,sticky_fault,
    output wire [63:0] measured_deltas,
    output wire [10:0] sampled_status,output wire [3:0] ever_healthy,live_fault
);
    localparam integer WINDOW_W=$clog2(WINDOW_CYCLES)<1?1:$clog2(WINDOW_CYCLES);
    localparam integer HEART_W=$clog2(HEARTBEAT_CYCLES)<1?1:$clog2(HEARTBEAT_CYCLES);
    wire [WINDOW_W-1:0] window_count;
    wire window_tick=window_count==WINDOW_CYCLES-1;
    wire [HEART_W-1:0] heart_count;
    wire heartbeat;
    board_diag_reg #(.WIDTH(WINDOW_W)) u_window(.clk(ref_clk),.d(window_tick?{WINDOW_W{1'b0}}:window_count+1'b1),.q(window_count));
    board_diag_reg #(.WIDTH(HEART_W)) u_heart_count(.clk(ref_clk),
        .d(heart_count==HEARTBEAT_CYCLES-1?{HEART_W{1'b0}}:heart_count+1'b1),.q(heart_count));
    board_diag_reg u_heartbeat(.clk(ref_clk),.d(heartbeat^(heart_count==HEARTBEAT_CYCLES-1)),.q(heartbeat));
    (* syn_preserve=1 *) wire [4:0] key_meta,key_sync;
    board_diag_reg #(.WIDTH(5),.INIT(5'b11111)) u_key_meta(.clk(ref_clk),.d(key_n),.q(key_meta));
    board_diag_reg #(.WIDTH(5),.INIT(5'b11111)) u_key_sync(.clk(ref_clk),.d(key_meta),.q(key_sync));
    // One extra stage compared with the key path disarms history before the
    // expected PLL/reset changes from a KEY0 press become visible here.
    (* syn_preserve=1 *) wire [10:0] status_meta,status_mid,status_sync;
    board_diag_reg #(.WIDTH(11)) u_status_meta(.clk(ref_clk),
        .d({controller_led,eth_rst_n,audio_rst_n,common_arst_n,pll_lock}),.q(status_meta));
    board_diag_reg #(.WIDTH(11)) u_status_mid(.clk(ref_clk),.d(status_meta),.q(status_mid));
    board_diag_reg #(.WIDTH(11)) u_status_sync(.clk(ref_clk),.d(status_mid),.q(status_sync));
    genvar i;
    generate for(i=0;i<4;i=i+1) begin:g_frequency
        localparam integer RATE=(i==1)?96000000:((i==2)?122880000:125000000);
        board_diag_frequency #(.TARGET_HZ(RATE),.WINDOW_CYCLES(WINDOW_CYCLES),.PRESCALE_BITS(PRESCALE_BITS)) u_frequency(
            .clk(ref_clk),.window_tick(window_tick),.restart((i!=0)&&!key_sync[0]),.gray_async(clocks_gray[i*16+:16]),
            .good(frequency_good[i]),.last_delta(measured_deltas[i*16+:16]));
    end endgenerate
    wire clear_history=!key_sync[3] && !key_sync[4];
    wire [3:0] healthy={status_sync[2:0]&frequency_good[3:1],&status_sync[5:3]};
    wire [3:0] armed;
    board_diag_reg #(.WIDTH(4)) u_armed(.clk(ref_clk),
        .d((clear_history || !key_sync[0])?4'b0:(armed|healthy)),.q(armed));
    board_diag_reg #(.WIDTH(4)) u_fault(.clk(ref_clk),
        .d(clear_history?4'b0:(sticky_fault | (key_sync[0]?(armed&~healthy):4'b0))),.q(sticky_fault));
    reg [4:0] display;
    always @* begin
        display={status_sync[3],status_sync[2:0],heartbeat};
        if(clear_history) display={4'b0,heartbeat};
        else if(!key_sync[4]) display={sticky_fault,heartbeat};
        else if(!key_sync[3]) display=status_sync[10:6];
        else if(!key_sync[2]) display={status_sync[5:3],!key_sync[0],heartbeat};
        else if(!key_sync[1]) display={frequency_good,heartbeat};
    end
    assign led=display;
    assign sampled_status=status_sync;
    assign ever_healthy=armed;
    assign live_fault=~healthy;
endmodule
