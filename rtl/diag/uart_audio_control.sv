`timescale 1ns/1ps
// Independent line protocol. '@' owns bytes through CR/LF, so letters inside
// framed commands can never invoke legacy one-byte reset/test commands.
// I2S1/GAIN1 + fourteen hex words + CRLF; see host parser for field names.
module uart_audio_control #(
    parameter integer SNAPSHOT_WAIT=128,COMMAND_TIMEOUT=27000000
)(
    input wire clk,rst_n,input wire [7:0] rx_data,input wire rx_valid,rx_error,
    output wire legacy_valid,
    output reg desired_enable,output reg [6:0] desired_channel,
    output reg [23:0] desired_even_gain,desired_odd_gain,
    input wire config_pending,audio_reset_released,
    output reg snapshot_launch,input wire [255:0] snapshot_data,input wire snapshot_fresh,
    output wire [7:0] tx_data,output wire tx_valid,tx_last,input wire tx_ready
);
    reg collecting,overflow;
    reg [4:0] length;
    reg [143:0] buffer;
    // Fixed byte slices avoid synthesis of a loop-carried integer accumulator
    // and variable shifts. Ten bits retain 000..999 for the range check.
    wire [7:0] decimal_ones=buffer[7:0],decimal_tens=buffer[15:8],decimal_hundreds=buffer[23:16];
    wire ones_valid=decimal_ones>=8'h30 && decimal_ones<=8'h39;
    wire tens_valid=decimal_tens>=8'h30 && decimal_tens<=8'h39;
    wire hundreds_valid=decimal_hundreds>=8'h30 && decimal_hundreds<=8'h39;
    wire [9:0] one_digit={6'b0,decimal_ones[3:0]};
    wire [9:0] two_digits={6'b0,decimal_tens[3:0]}*10'd10+one_digit;
    wire [9:0] three_digits={6'b0,decimal_hundreds[3:0]}*10'd100+two_digits;
    reg [31:0] command_timer;
    wire finish=rx_valid && collecting && (rx_data==13 || rx_data==10);
    assign legacy_valid=rx_valid && !collecting && rx_data!="@";
    reg parsed_gain,parsed_set,parsed_enable;
    reg [6:0] parsed_channel;
    reg [23:0] parsed_even,parsed_odd;
    reg [7:0] parsed_error;
    integer k,digit;
    function automatic integer hex_digit(input [7:0] c);
        begin
            if(c>="0" && c<="9")hex_digit=c-"0";
            else if(c>="A" && c<="F")hex_digit=c-"A"+10;
            else if(c>="a" && c<="f")hex_digit=c-"a"+10;
            else hex_digit=-1;
        end
    endfunction
    always @* begin
        parsed_gain=length>=4 && (buffer >> ((length-4)*8))=="GAIN";
        parsed_set=0;parsed_enable=desired_enable;parsed_channel=desired_channel;
        parsed_even=desired_even_gain;parsed_odd=desired_odd_gain;parsed_error=1;
        digit=0;
        if(!overflow)begin
            if(length==4 && buffer=="I2S?")parsed_error=0;
            else if(length==5 && buffer=="GAIN?")begin parsed_gain=1;parsed_error=0;end
            else if(length==7 && buffer=="I2S=OFF")begin parsed_set=1;parsed_enable=0;parsed_error=0;end
            else if(length==5 && buffer[39:8]=="I2S=")begin
                parsed_set=1;parsed_enable=1;parsed_channel=one_digit[6:0];
                parsed_error=ones_valid?8'd0:8'd1;
            end else if(length==6 && buffer[47:16]=="I2S=")begin
                parsed_set=1;parsed_enable=1;parsed_channel=two_digits[6:0];
                parsed_error=ones_valid && tens_valid?8'd0:8'd1;
            end else if(length==7 && buffer[55:24]=="I2S=")begin
                parsed_set=1;parsed_enable=1;parsed_channel=three_digits[6:0];
                if(!ones_valid || !tens_valid || !hundreds_valid)parsed_error=1;
            else parsed_error=(three_digits>10'd127) ? 8'd2 : 8'd0;
            end else if(length==18 && buffer[143:104]=="GAIN=" && buffer[55:48]==",")begin
                parsed_gain=1;parsed_set=1;parsed_error=0;parsed_even=0;parsed_odd=0;
                for(k=0;k<6;k=k+1)begin
                    digit=hex_digit(buffer[103-k*8 -: 8]);
                    if(digit<0)parsed_error=1;else parsed_even={parsed_even[19:0],digit[3:0]};
                    digit=hex_digit(buffer[47-k*8 -: 8]);
                    if(digit<0)parsed_error=1;else parsed_odd={parsed_odd[19:0],digit[3:0]};
                end
                if(parsed_even[23] || parsed_odd[23])parsed_error=2;
            end
        end
    end
    // Eight requests may wait behind a complete SYS3 or audio response line.
    // Beyond that, reject the configuration and expose the drop count. Host
    // tools send one command at a time and therefore never depend on flooding.
    reg queue_gain[0:7];reg [7:0] queue_error[0:7];
    reg [2:0] head,tail;reg [3:0] count;
    reg [15:0] queue_overflow;
    reg active,waiting,active_gain;
    reg [7:0] active_error;
    reg [15:0] wait_count;
    reg [7:0] index;
    reg [31:0] sequence_count;
    reg [447:0] response;
    wire push=finish && count<8;
    wire pop=!active && !waiting && count!=0;
    wire fresh=snapshot_fresh && audio_reset_released;
    wire pending=config_pending || !fresh || snapshot_data[31:24]!={desired_enable,desired_channel} ||
        snapshot_data[151:128]!=desired_even_gain || snapshot_data[183:160]!=desired_odd_gain;
    reg [7:0] character;
    reg [3:0] nibble;
    integer word_index,nibble_index;
    wire [7:0] first_word=active_gain?8'd6:8'd5;
    wire [7:0] last_index=active_gain?8'd132:8'd131;
    always @* begin
        character=32;nibble=0;word_index=0;nibble_index=0;
        case(index)
            0:character=active_gain?"G":"I";
            1:character=active_gain?"A":"2";
            2:character=active_gain?"I":"S";
            3:character=active_gain?"N":"1";
            4:character=active_gain?"1":" ";
            default:begin end
        endcase
        if(index>=first_word && index<last_index-1)begin
            word_index=(index-first_word)/9;nibble_index=(index-first_word)%9;
            if(nibble_index<8)begin
                nibble=response >> (word_index*32+(7-nibble_index)*4);
                character=nibble<10?8'h30+nibble:8'h41+nibble-10;
            end
        end
        if(index==last_index-1)character=13;
        if(index==last_index)character=10;
    end
    assign tx_data=character;
    assign tx_valid=active;
    assign tx_last=index==last_index;
    always @(posedge clk)begin
        if(!rst_n)begin
            collecting<=0;overflow<=0;length<=0;buffer<=0;command_timer<=0;
            desired_enable<=1;desired_channel<=0;desired_even_gain<=24'h400000;desired_odd_gain<=24'h400000;
            head<=0;tail<=0;count<=0;queue_overflow<=0;active<=0;waiting<=0;
            active_gain<=0;active_error<=0;wait_count<=0;index<=0;sequence_count<=0;response<=0;snapshot_launch<=0;
        end else begin
            snapshot_launch<=0;
            if(collecting)begin
                if(command_timer==COMMAND_TIMEOUT-1)begin collecting<=0;overflow<=0;length<=0;end
                else command_timer<=command_timer+1'b1;
            end
            if(rx_valid)begin
                if(!collecting && rx_data=="@")begin collecting<=1;overflow<=0;length<=0;buffer<=0;command_timer<=0;end
                else if(collecting)begin
                    command_timer<=0;
                    if(finish)begin collecting<=0;overflow<=0;length<=0;end
                    else if(length==18)overflow<=1;
                    else begin buffer<={buffer[135:0],rx_data};length<=length+1'b1;end
                end
            end
            if(rx_error && collecting)overflow<=1;
            if(push)begin
                queue_gain[tail]<=parsed_gain;queue_error[tail]<=parsed_error;tail<=tail+1'b1;
                if(parsed_error==0 && parsed_set)begin
                    if(parsed_gain)begin desired_even_gain<=parsed_even;desired_odd_gain<=parsed_odd;end
                    else begin desired_enable<=parsed_enable;desired_channel<=parsed_channel;end
                end
            end else if(finish)queue_overflow<=queue_overflow+1'b1;
            if(pop)begin
                active_gain<=queue_gain[head];active_error<=queue_error[head];head<=head+1'b1;
                snapshot_launch<=1;waiting<=1;wait_count<=SNAPSHOT_WAIT;
            end
            case({push,pop})2'b10:count<=count+1'b1;2'b01:count<=count-1'b1;default:begin end endcase
            if(waiting)begin
                if(wait_count!=0)wait_count<=wait_count-1'b1;
                else begin
                    response[31:0]<=sequence_count;
                    response[63:32]<={queue_overflow,active_error,5'b0,audio_reset_released,pending,fresh};
                    response[95:64]<={24'b0,desired_enable,desired_channel};
                    response[127:96]<=fresh?{24'b0,snapshot_data[31:24]}:32'b0;
                    response[159:128]<={8'b0,desired_even_gain};response[191:160]<={8'b0,desired_odd_gain};
                    response[223:192]<=fresh?{8'b0,snapshot_data[151:128]}:32'b0;
                    response[255:224]<=fresh?{8'b0,snapshot_data[183:160]}:32'b0;
                    response[287:256]<=fresh?snapshot_data[63:32]:32'b0;
                    response[319:288]<=fresh?snapshot_data[95:64]:32'b0;
                    response[351:320]<=fresh?snapshot_data[127:96]:32'b0;
                    response[383:352]<=fresh?{8'b0,snapshot_data[23:0]}:32'b0;
                    response[415:384]<=fresh?snapshot_data[223:192]:32'b0;
                    response[447:416]<=fresh?snapshot_data[255:224]:32'b0;
                    sequence_count<=sequence_count+1'b1;waiting<=0;active<=1;index<=0;
                end
            end
            if(active && tx_ready)begin
                if(tx_last)begin active<=0;index<=0;end else index<=index+1'b1;
            end
        end
    end
endmodule
