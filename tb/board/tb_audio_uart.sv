`timescale 1ns/1ps
// Pin-level UART protocol, line arbitration and reset/stopped-clock CDC tests.
module tb_audio_uart;
    reg ref_clk=0,audio_clk=0,audio_run=1,uart_rx=1,external_audio_reset_n=0;
    always #10 ref_clk=~ref_clk;
    always #4 if(audio_run)audio_clk=~audio_clk;
    wire tx,system_reset_n,mode_key_n;
    wire audio_rst_n=external_audio_reset_n && system_reset_n;
    wire cfg_enable,cfg_valid;
    wire [6:0] cfg_channel;
    wire [23:0] cfg_even,cfg_odd;
    reg cfg_ready=1;
    reg active_enable=0;
    reg [6:0] active_channel=0;
    reg [23:0] active_even=24'h400000,active_odd=24'h400000;
    reg [23:0] pending_even,pending_odd;
    reg gain_pending=0;
    reg [9:0] frame_timer=0;
    reg [31:0] frames=0,received=0;
    wire [255:0] status={32'd0,frames,8'b0,active_odd,8'b0,active_even,32'd3,frames,received,
        active_enable,active_channel,24'h123456};
    always @(posedge audio_clk or negedge audio_rst_n)begin
        if(!audio_rst_n)begin
            active_enable<=0;active_channel<=0;active_even<=24'h400000;active_odd<=24'h400000;
            gain_pending<=0;frame_timer<=0;frames<=0;received<=0;
        end else begin
            frame_timer<=frame_timer+1'b1;
            if(cfg_valid && cfg_ready)begin pending_even<=cfg_even;pending_odd<=cfg_odd;gain_pending<=1;end
            if(frame_timer==1023)begin
                active_enable<=cfg_enable;active_channel<=cfg_channel;frames<=frames+1'b1;received<=received+1'b1;
                if(gain_pending)begin active_even<=pending_even;active_odd<=pending_odd;gain_pending<=0;end
            end
        end
    end
    board_uart_diagnostics #(.UART_DIV(8),.REPORT_CYCLES(12000),.MS_CYCLES(50),
        .RESET_CYCLES(32),.MODE_KEY_CYCLES(64),.WINDOW_CYCLES(2048),.PRESCALE_BITS(6)) dut(
        .ref_clk(ref_clk),.raw125_clk(audio_clk),.clk96(audio_clk),.audio_clk(audio_clk),.eth_clk(audio_clk),.rx_clk(audio_clk),
        .uart_rx(uart_rx),.physical_reset_n(1'b1),.pll_lock(3'b111),.common_arst_n(audio_rst_n),
        .audio_rst_n(audio_rst_n),.eth_rst_n(audio_rst_n),.controller_led(5'b0),
        .audio_status(128'b0),.rx_status(128'b0),.eth_status(576'b0),.i2s_status(status),.audio_gain_cfg_ready(cfg_ready),
        .audio_i2s_enable(cfg_enable),.audio_i2s_channel(cfg_channel),.audio_even_gain(cfg_even),.audio_odd_gain(cfg_odd),
        .audio_gain_cfg_valid(cfg_valid),.uart_tx(tx),.system_reset_n(system_reset_n),.mode_key_n(mode_key_n));
    integer checks=0,sys_lines=0,audio_lines=0,raw_file;
    reg [31:0] response[0:13];
    reg [31:0] sys_words[0:33];
    string line="",token,last_tag="";
    task automatic check(input bit ok,input string detail);
        begin checks++;if(!ok)$fatal(1,"[TB_ERROR] %s at %t",detail,$time);end
    endtask
    task automatic send_byte(input byte c);
        integer k;
        begin
            @(negedge ref_clk);uart_rx=0;repeat(8)@(negedge ref_clk);
            for(k=0;k<8;k++)begin uart_rx=c[k];repeat(8)@(negedge ref_clk);end
            uart_rx=1;repeat(12)@(negedge ref_clk);
        end
    endtask
    task automatic command(input string text);
        integer k;
        begin for(k=0;k<text.len();k++)send_byte(text.getc(k));end
    endtask
    task automatic exchange(input string text,input string tag,input integer error_code);
        integer previous;
        begin
            $display("[TB_MONITOR] command=%s expected_error=%0d",text,error_code);
            previous=audio_lines;command(text);wait(audio_lines>previous);
            $display("[TB_DATA] tag=%s error=%0d flags=%h desired=%h active=%h",last_tag,response[1][15:8],response[1],response[2],response[3]);
            check(last_tag==tag,"response kind");check(response[1][15:8]==error_code,"response error code");
        end
    endtask
    byte value;
    integer k,w,n,offset;
    initial forever begin
        @(negedge tx);repeat(4)@(posedge ref_clk);check(tx===0,"UART start");
        for(k=0;k<8;k++)begin repeat(8)@(posedge ref_clk);value[k]=tx;end
        repeat(8)@(posedge ref_clk);check(tx===1,"UART stop");
        if(value==10)begin
            $fwrite(raw_file,"%s\n",line);
            if(line.substr(0,4)=="SYS3 ")begin
                check(line.len()==311,"SYS3 unchanged length, no audio interleaving");
                for(w=0;w<34;w++)begin token=line.substr(5+w*9,12+w*9);n=$sscanf(token,"%h",sys_words[w]);check(n==1,"SYS3 word");end
                check(sys_words[0]==sys_lines,"SYS3 consecutive sequence");sys_lines++;
            end else begin
                if(line.substr(0,4)=="GAIN1")begin offset=6;last_tag="GAIN1";check(line.len()==132,"GAIN1 length");end
                else begin offset=5;last_tag="I2S1";check(line.substr(0,4)=="I2S1 ","independent audio identifier");check(line.len()==131,"I2S1 length");end
                for(w=0;w<14;w++)begin
                    token=line.substr(offset+w*9,offset+7+w*9);n=$sscanf(token,"%h",response[w]);
                    check(n==1 && !$isunknown(response[w]),"audio response defined hex word");
                    if(w<13)check(line.getc(offset+8+w*9)==32,"audio separator");
                end
                check(response[0]==audio_lines,"audio consecutive sequence");audio_lines++;
            end
            check(line.getc(line.len()-1)==13,"CRLF framing");line="";
        end else line={line,value};
    end
    integer before_legacy,before_lines;
    integer selected;
    reg [47:0] held_gains;
    initial begin
        raw_file=$fopen("../log/audio_uart/rtl_uart.log","w");check(raw_file!=0,"log open");
        repeat(50)@(negedge ref_clk);external_audio_reset_n=1;wait(sys_lines>=1);
        exchange("@I2S?\n","I2S1",0);check(response[1][0] && !response[1][1] && response[3]==128,"default active channel0");
        exchange("@I2S=127\n","I2S1",0);exchange("@I2S?\n","I2S1",0);
        check(response[2]==255 && response[3]==255 && !response[1][1],"channel127 applied");
        exchange({"@I2S=0",8'h0d,8'h0a},"I2S1",0);exchange("@I2S?\n","I2S1",0);check(response[3]==128,"channel0 applied");
        exchange("@I2S=OFF\n","I2S1",0);exchange("@I2S?\n","I2S1",0);check(response[3]==0 && !response[1][1],"OFF preserves clocks, muted active state");
        exchange("@I2S=128\n","I2S1",2);check(response[2]==0,"invalid channel cannot change configuration");
        exchange("@I2S=999\n","I2S1",2);check(response[2]==0,"three-digit range cannot truncate to seven bits");
        exchange("@I2S=-1\n","I2S1",1);exchange("@I2S=xyz\n","I2S1",1);
        for(selected=0;selected<128;selected++)begin
            exchange($sformatf("@I2S=%0d\n",selected),"I2S1",0);
            exchange("@I2S?\n","I2S1",0);
            check(response[2]==128+selected && response[3]==128+selected && !response[1][1],"all decimal channels requested and actually applied");
        end
        exchange("@I2S=007\n","I2S1",0);exchange("@I2S?\n","I2S1",0);check(response[3]==135,"leading zero decimal remains decimal");
        exchange("@I2S=OFF\n","I2S1",0);exchange("@I2S?\n","I2S1",0);
        exchange("@GAIN=200000,600000\n","GAIN1",0);exchange("@GAIN?\n","GAIN1",0);
        check(response[4]==24'h200000 && response[5]==24'h600000 && response[6]==24'h200000 && response[7]==24'h600000,"actual even/odd gains");
        exchange("@GAIN=800000,400000\n","GAIN1",2);check(response[4]==24'h200000,"negative gain rejected");
        exchange("@GAIN=000000,7fffff\n","GAIN1",0);exchange("@GAIN?\n","GAIN1",0);
        check(response[6]==0 && response[7]==24'h7fffff,"zero and maximum positive gain");
        exchange("@GAIN=GG0000,400000\n","GAIN1",1);
        cfg_ready=0;exchange("@GAIN=300000,500000\n","GAIN1",0);
        check(response[1][1] && response[6]==0 && response[7]==24'h7fffff,"pending while cfg READY blocked, actual gain retained");
        wait(cfg_valid);held_gains={cfg_even,cfg_odd};repeat(300)@(posedge ref_clk);
        check(cfg_valid && {cfg_even,cfg_odd}==held_gains,"bundled coefficients stable under backpressure");
        cfg_ready=1;exchange("@GAIN?\n","GAIN1",0);check(response[6]==24'h300000 && response[7]==24'h500000 && !response[1][1],"backpressure recovery");
        before_legacy=dut.command_count;exchange("@I2S=strch\n","I2S1",1);
        check(dut.command_count==before_legacy && mode_key_n && system_reset_n,"legacy letters inside malformed frame suppressed");
        before_lines=audio_lines;command("@I2S=5\n@I2S?\n@GAIN?\n");wait(audio_lines==before_lines+3);
        check(sys_lines>=2,"SYS3 remains live beside queued audio replies");
        @(negedge audio_clk);audio_run=0;
        exchange("@I2S=17\n","I2S1",0);check(!response[1][0] && response[1][1],"stopped source fresh0 pending1, UART responsive");
        exchange("@GAIN?\n","GAIN1",0);check(!response[1][0],"stopped source cannot certify gain snapshot");
        audio_run=1;exchange("@I2S?\n","I2S1",0);exchange("@I2S?\n","I2S1",0);
        check(response[1][0] && !response[1][1] && response[3]==145,"clock resumes, desired channel17 replayed");
        #3;external_audio_reset_n=0;#2;external_audio_reset_n=1;
        exchange("@GAIN?\n","GAIN1",0);exchange("@I2S?\n","I2S1",0);
        check(response[3]==145 && response[6]==24'h300000 && response[7]==24'h500000 && !response[1][1],"short audio reset automatically replays all config");
        before_legacy=dut.command_count;send_byte("t");wait(!mode_key_n);wait(mode_key_n);
        send_byte("c");send_byte("s");send_byte("h");send_byte("r");wait(!system_reset_n);wait(system_reset_n);
        exchange("@I2S?\n","I2S1",0);check(dut.command_count==before_legacy+5 && dut.unknown_count==0,"legacy command compatibility, no audio bytes counted unknown");
        check(response[3]==145 && response[6]==24'h300000,"system reset retains supervisor configuration");
        $fclose(raw_file);$display("[TB_DATA] Audio UART syntax, actual state, no interleaving, stopped clock and reset replay PASS");
        $display("[TB_INFO] Simulation Finished! checks=%0d SYS3=%0d audio=%0d",checks,sys_lines,audio_lines);$finish;
    end
    initial begin #500000000;$fatal(1,"[TB_ERROR] audio UART timeout");end
endmodule
module GTP_DFF #(parameter GRS_EN="TRUE",parameter INIT=1'b0)(input wire CLK,D,output reg Q=INIT);
    always @(posedge CLK)Q<=D;
endmodule
