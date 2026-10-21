`timescale 1ns/1ps
// Runs against the unmodified PDS technology netlist, never the RTL source.
module tb_vendor_uart;
    reg clk=0,rst_n=0;
    always #10 clk=~clk;
    reg [7:0] rx_data=0;
    reg rx_valid=0,rx_error=0,tx_ready=1;
    wire legacy_valid,desired_enable,snapshot_launch,tx_valid,tx_last;
    wire [6:0] desired_channel;
    wire [23:0] desired_even_gain,desired_odd_gain;
    wire [7:0] tx_data;
    wire [255:0] snapshot_data={32'd0,32'd9,8'b0,desired_odd_gain,
        8'b0,desired_even_gain,32'd0,32'd9,32'd9,
        desired_enable,desired_channel,24'h123456};
    uart_audio_control dut(.clk(clk),.rst_n(rst_n),.rx_data(rx_data),
        .rx_valid(rx_valid),.rx_error(rx_error),.legacy_valid(legacy_valid),
        .desired_enable(desired_enable),.desired_channel(desired_channel),
        .desired_even_gain(desired_even_gain),.desired_odd_gain(desired_odd_gain),
        .config_pending(1'b0),.audio_reset_released(1'b1),
        .snapshot_launch(snapshot_launch),.snapshot_data(snapshot_data),
        .snapshot_fresh(1'b1),.tx_data(tx_data),.tx_valid(tx_valid),
        .tx_last(tx_last),.tx_ready(tx_ready));
    integer checks=0,lines=0,size=0,cycles=0,legacy_count=0;
    byte line_bytes[0:255];
    reg [31:0] response[0:13];
    string tag;
    reg [6:0] seen_zero=0,seen_one=0;
    task automatic check(input bit condition,input string message);
        begin
            checks=checks+1;
            if(!condition)begin $display("[TB_ERROR] %s",message);$fatal(1);end
        end
    endtask
    function automatic integer hex_value(input byte value);
        if(value>=48 && value<=57)hex_value=value-48;
        else if(value>=65 && value<=70)hex_value=value-65+10;
        else hex_value=-1;
    endfunction
    integer off,w,n,h;
    always @(posedge clk)begin
        cycles=cycles+1;
        if(rst_n)begin
            if(legacy_valid)legacy_count=legacy_count+1;
            if(tx_valid && tx_ready)begin
                check(size<255,"response line overflow");
                if(tx_data==10)begin
                    check(tx_last,"last marker absent from LF");
                    if(line_bytes[0]==73)begin tag="I2S1";off=5;check(size==131,"I2S line size");end
                    else begin tag="GAIN1";off=6;check(size==132,"GAIN line size");end
                    for(w=0;w<14;w=w+1)begin
                        response[w]=0;
                        for(n=0;n<8;n=n+1)begin
                            h=hex_value(line_bytes[off+w*9+n]);
                            check(h>=0,"non-hex response");
                            response[w]={response[w][27:0],h[3:0]};
                        end
                    end
                    check(line_bytes[size-1]==13,"response CR missing");
                    lines=lines+1;size=0;
                end else begin check(!tx_last,"premature last marker");line_bytes[size]=tx_data;size=size+1;end
            end
        end
    end
    always @(negedge clk)tx_ready=(cycles%7)!=3;
    task automatic send_byte(input byte data);
        begin @(negedge clk);rx_data=data;rx_valid=1;@(negedge clk);rx_valid=0;end
    endtask
    task automatic exchange(input string command,input string expected_tag,input integer error_code);
        integer old_lines,i,wait_cycles;
        begin
            old_lines=lines;
            for(i=0;i<command.len();i=i+1)send_byte(command.getc(i));
            wait_cycles=0;
            while(lines==old_lines && wait_cycles<1200)begin @(negedge clk);wait_cycles=wait_cycles+1;end
            check(lines==old_lines+1,{"response timeout: ",command});
            check(tag==expected_tag,"response tag mismatch");
            check(response[1][15:8]==error_code,"error code mismatch");
            check(response[1][0] && !response[1][1],"fresh response marked pending");
        end
    endtask
    task automatic state_check(input integer selected,input bit enabled);
        begin
            check(desired_channel===selected[6:0],"desired channel mismatch");
            check(desired_enable===enabled,"desired enable mismatch");
            check(response[2]=={24'b0,enabled,selected[6:0]},"reply desired channel mismatch");
            check(response[3]=={24'b0,enabled,selected[6:0]},"reply actual channel mismatch");
            seen_zero=seen_zero|~desired_channel;seen_one=seen_one|desired_channel;
        end
    endtask
    integer selected,before_legacy;
    initial begin
        repeat(20)@(negedge clk);rst_n=1;repeat(5)@(negedge clk);
        check(desired_channel===0 && desired_enable===1,"reset channel/enable");
        check(desired_even_gain===24'h400000 && desired_odd_gain===24'h400000,"reset gains");
        for(selected=0;selected<128;selected=selected+1)begin
            exchange($sformatf("@I2S=%0d\n",selected),"I2S1",0);state_check(selected,1);
        end
        check(seen_zero==7'h7f && seen_one==7'h7f,"all seven channel bits must toggle");
        exchange("@I2S=128\n","I2S1",2);state_check(127,1);
        exchange("@I2S=999\n","I2S1",2);state_check(127,1);
        before_legacy=legacy_count;
        exchange("@I2S=1x7\n","I2S1",1);state_check(127,1);
        exchange("@I2S=-1\n","I2S1",1);state_check(127,1);
        exchange("@I2S=xyz\n","I2S1",1);state_check(127,1);
        exchange("@I2S=strch\n","I2S1",1);state_check(127,1);
        check(legacy_count==before_legacy,"framed invalid command leaked to legacy");
        exchange("@I2S=007\n","I2S1",0);state_check(7,1);
        exchange("@I2S=OFF\n","I2S1",0);state_check(7,0);
        exchange("@I2S?\n","I2S1",0);state_check(7,0);
        exchange("@I2S=42\n","I2S1",0);state_check(42,1);
        exchange("@GAIN=200000,600000\n","GAIN1",0);
        check(desired_even_gain==24'h200000 && desired_odd_gain==24'h600000,"non-unity gain update");
        check(response[4]==32'h200000 && response[5]==32'h600000 && response[6]==32'h200000 && response[7]==32'h600000,"gain reply data");
        exchange("@GAIN=800000,400000\n","GAIN1",2);
        check(desired_even_gain==24'h200000 && desired_odd_gain==24'h600000,"out of range gain changed state");
        exchange("@GAIN=GG0000,400000\n","GAIN1",1);
        check(desired_even_gain==24'h200000 && desired_odd_gain==24'h600000,"invalid gain changed state");
        exchange("@GAIN=000000,7fffff\n","GAIN1",0);
        check(desired_even_gain==0 && desired_odd_gain==24'h7fffff,"gain boundary update");
        exchange("@GAIN?\n","GAIN1",0);
        $display("[TB_DATA] gate_channels=128 channel_bit_zero_mask=%02x channel_bit_one_mask=%02x checks=%0d lines=%0d",seen_zero,seen_one,checks,lines);
        $display("[TB_INFO] Simulation Finished!");$finish;
    end
    initial begin #10000000;$display("[TB_ERROR] global timeout");$fatal(1);end
endmodule
