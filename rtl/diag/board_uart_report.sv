`timescale 1ns/1ps
// SYS3 + 34 hex words (seq,ms,32 status words), separated by spaces, CRLF.
// One immutable snapshot per line. Pending requests coalesce while UART busy.
module board_uart_report #(
    parameter integer UART_DIV=234,REPORT_CYCLES=6750000,MS_CYCLES=27000,SNAPSHOT_WAIT=64
)(
    input wire clk,rst_n,request,input wire [1023:0] status_words,
    input wire [7:0] aux_data,input wire aux_valid,aux_last,output wire aux_ready,
    output reg snapshot_launch,output wire tx
);
    localparam integer LINE_LEN=312;
    reg [31:0] ms_count,milliseconds,period_count,sequence_count;
    reg [1087:0] snapshot;
    reg [8:0] index;
    reg [15:0] wait_count;
    reg active,pending,collecting;
    reg [7:0] character;
    reg [1:0] owner;
    wire choose_aux=owner==2 || (owner==0 && aux_valid);
    wire choose_sys=owner==1 || (owner==0 && !aux_valid && active);
    wire send_valid=(choose_aux && aux_valid)||(choose_sys && active);
    wire [7:0] send_data=choose_aux?aux_data:character;
    wire tx_ready;
    integer word_index,nibble_index;
    reg [3:0] nibble;
    always @* begin
        character=8'h20;word_index=0;nibble_index=0;nibble=0;
        case(index)
            0:character="S";1:character="Y";2:character="S";3:character="3";
            310:character=8'h0d;311:character=8'h0a;
            default:if(index>=5 && index<310)begin
                word_index=(index-5)/9;nibble_index=(index-5)%9;
                if(nibble_index<8)begin
                    nibble=(snapshot >> (word_index*32+(7-nibble_index)*4));
                    character=nibble<10 ? 8'h30+nibble : 8'h41+nibble-10;
                end
            end
        endcase
    end
    diag_uart_tx #(.CLKS_PER_BIT(UART_DIV)) transmitter(.clk(clk),.rst_n(rst_n),
        .data(send_data),.valid(send_valid),.ready(tx_ready),.tx(tx));
    assign aux_ready=choose_aux && tx_ready;
    always @(posedge clk) begin
        if(!rst_n)begin
            ms_count<=0;milliseconds<=0;period_count<=0;sequence_count<=0;snapshot<=0;
            index<=0;wait_count<=0;active<=0;pending<=1;collecting<=0;snapshot_launch<=0;owner<=0;
        end else begin
            snapshot_launch<=0;
            if(ms_count==MS_CYCLES-1)begin ms_count<=0;milliseconds<=milliseconds+1'b1;end
            else ms_count<=ms_count+1'b1;
            if(period_count==REPORT_CYCLES-1)period_count<=0;else period_count<=period_count+1'b1;
            if(!active && !collecting && pending)begin
                snapshot_launch<=1;collecting<=1;wait_count<=SNAPSHOT_WAIT;pending<=0;
            end
            if(collecting)begin
                if(wait_count!=0)wait_count<=wait_count-1'b1;
                else begin
                    snapshot<={status_words,milliseconds,sequence_count};
                    sequence_count<=sequence_count+1'b1;collecting<=0;active<=1;index<=0;
                end
            end
            if(send_valid && tx_ready)begin
                if(choose_aux)owner<=aux_last?0:2;
                else owner<=index==LINE_LEN-1?0:1;
            end
            if(active && choose_sys && tx_ready)begin
                if(index==LINE_LEN-1)begin active<=0;index<=0;end
                else index<=index+1'b1;
            end
            if(request || period_count==REPORT_CYCLES-1)pending<=1;
        end
    end
endmodule
