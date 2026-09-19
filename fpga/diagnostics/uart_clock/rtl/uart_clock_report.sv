`timescale 1ns/1ps
// Fixed ASCII frames; each complete line uses one coherent 27 MHz snapshot.
module uart_clock_report #(
    parameter integer UART_DIV=234,REPORT_CYCLES=6750000,MS_CYCLES=27000
)(
    input wire clk,rst_n,request,input wire [10:0] sampled_status,
    input wire [3:0] frequency_good,seen,fault,live_fault,input wire [63:0] deltas,
    input wire reset_active,input wire [15:0] command_count,rx_error_count,
    input wire [7:0] last_command,output wire tx
);
    localparam integer LINE_LEN=159;
    localparam [8*LINE_LEN-1:0] TEMPLATE="CLK2 pfd=31.25 seq=00000000 ms=00000000 lock=000 rst=000 freq=0000 delta=0000,0000,0000,0000 seen=0 fault=0 now=0 ctrl=00 reset=0 cmd=00 cmds=0000 rxerr=0000\015\012";
    reg [31:0] milliseconds,ms_count,report_count,sequence_count;
    reg active,pending;
    reg [7:0] index;
    reg [31:0] snap_seq,snap_ms;
    reg [10:0] snap_status;
    reg [3:0] snap_good,snap_seen,snap_fault,snap_live;
    reg [63:0] snap_deltas;
    reg snap_reset;
    reg [7:0] snap_command;
    reg [15:0] snap_commands,snap_errors;
    wire timer_tick=report_count==REPORT_CYCLES-1;
    wire ready;
    function automatic [7:0] hex_digit(input [3:0] nibble);
        hex_digit=nibble<10?(8'h30+nibble):(8'h41+nibble-10);
    endfunction
    function automatic [7:0] character(input [7:0] offset);
        begin
            character=TEMPLATE[(LINE_LEN-1-offset)*8+:8];
            case(offset)
            19: character=hex_digit((snap_seq >> 28) & 4'hf);
            20: character=hex_digit((snap_seq >> 24) & 4'hf);
            21: character=hex_digit((snap_seq >> 20) & 4'hf);
            22: character=hex_digit((snap_seq >> 16) & 4'hf);
            23: character=hex_digit((snap_seq >> 12) & 4'hf);
            24: character=hex_digit((snap_seq >> 8) & 4'hf);
            25: character=hex_digit((snap_seq >> 4) & 4'hf);
            26: character=hex_digit((snap_seq >> 0) & 4'hf);
            31: character=hex_digit((snap_ms >> 28) & 4'hf);
            32: character=hex_digit((snap_ms >> 24) & 4'hf);
            33: character=hex_digit((snap_ms >> 20) & 4'hf);
            34: character=hex_digit((snap_ms >> 16) & 4'hf);
            35: character=hex_digit((snap_ms >> 12) & 4'hf);
            36: character=hex_digit((snap_ms >> 8) & 4'hf);
            37: character=hex_digit((snap_ms >> 4) & 4'hf);
            38: character=hex_digit((snap_ms >> 0) & 4'hf);
            98: character=hex_digit((snap_seen >> 0) & 4'hf);
            106: character=hex_digit((snap_fault >> 0) & 4'hf);
            112: character=hex_digit((snap_live >> 0) & 4'hf);
            119: character=hex_digit((snap_status[10:6] >> 4) & 4'hf);
            120: character=hex_digit((snap_status[10:6] >> 0) & 4'hf);
            134: character=hex_digit((snap_command >> 4) & 4'hf);
            135: character=hex_digit((snap_command >> 0) & 4'hf);
            142: character=hex_digit((snap_commands >> 12) & 4'hf);
            143: character=hex_digit((snap_commands >> 8) & 4'hf);
            144: character=hex_digit((snap_commands >> 4) & 4'hf);
            145: character=hex_digit((snap_commands >> 0) & 4'hf);
            153: character=hex_digit((snap_errors >> 12) & 4'hf);
            154: character=hex_digit((snap_errors >> 8) & 4'hf);
            155: character=hex_digit((snap_errors >> 4) & 4'hf);
            156: character=hex_digit((snap_errors >> 0) & 4'hf);
            45: character=8'h30+snap_status[0];
            46: character=8'h30+snap_status[1];
            47: character=8'h30+snap_status[2];
            53: character=8'h30+snap_status[3];
            54: character=8'h30+snap_status[4];
            55: character=8'h30+snap_status[5];
            62: character=8'h30+snap_good[0];
            63: character=8'h30+snap_good[1];
            64: character=8'h30+snap_good[2];
            65: character=8'h30+snap_good[3];
            73: character=hex_digit(snap_deltas[12+:4]);
            74: character=hex_digit(snap_deltas[8+:4]);
            75: character=hex_digit(snap_deltas[4+:4]);
            76: character=hex_digit(snap_deltas[0+:4]);
            78: character=hex_digit(snap_deltas[28+:4]);
            79: character=hex_digit(snap_deltas[24+:4]);
            80: character=hex_digit(snap_deltas[20+:4]);
            81: character=hex_digit(snap_deltas[16+:4]);
            83: character=hex_digit(snap_deltas[44+:4]);
            84: character=hex_digit(snap_deltas[40+:4]);
            85: character=hex_digit(snap_deltas[36+:4]);
            86: character=hex_digit(snap_deltas[32+:4]);
            88: character=hex_digit(snap_deltas[60+:4]);
            89: character=hex_digit(snap_deltas[56+:4]);
            90: character=hex_digit(snap_deltas[52+:4]);
            91: character=hex_digit(snap_deltas[48+:4]);
            128: character=8'h30+snap_reset;
                default: begin end
            endcase
        end
    endfunction
    diag_uart_tx #(.CLKS_PER_BIT(UART_DIV)) transmitter(.clk(clk),.rst_n(rst_n),
        .data(character(index)),.valid(active),.ready(ready),.tx(tx));
    always @(posedge clk) begin
        if(!rst_n) begin
            milliseconds<=0;ms_count<=0;report_count<=0;sequence_count<=0;active<=0;pending<=1;index<=0;
            snap_seq<=0;snap_ms<=0;snap_status<=0;snap_good<=0;snap_seen<=0;snap_fault<=0;snap_live<=0;
            snap_deltas<=0;snap_reset<=1;snap_command<=0;snap_commands<=0;snap_errors<=0;
        end else begin
            if(ms_count==MS_CYCLES-1)begin ms_count<=0;milliseconds<=milliseconds+1'b1;end
            else ms_count<=ms_count+1'b1;
            if(timer_tick)report_count<=0;else report_count<=report_count+1'b1;
            if(!active && pending)begin
                active<=1;pending<=0;index<=0;
                snap_seq<=sequence_count;sequence_count<=sequence_count+1'b1;snap_ms<=milliseconds;
                snap_status<=sampled_status;snap_good<=frequency_good;snap_seen<=seen;
                snap_fault<=fault;snap_live<=live_fault;snap_deltas<=deltas;snap_reset<=reset_active;
                snap_command<=last_command;snap_commands<=command_count;snap_errors<=rx_error_count;
            end else if(active && ready)begin
                if(index==LINE_LEN-1)begin active<=0;index<=0;end
                else index<=index+1'b1;
            end
            // A request during an ongoing frame is retained for the next frame.
            // The extra cycle also lets command counters commit before snapshot.
            if(request || timer_tick)pending<=1;
        end
    end
endmodule
