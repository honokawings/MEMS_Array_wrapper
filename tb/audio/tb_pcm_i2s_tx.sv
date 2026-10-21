`timescale 1ns/1ps
module tb_pcm_i2s_tx;
    reg clk=0, rst_n=0, enable=0, pcm_valid=0;
    reg [6:0] selected_channel=0, pcm_channel=0;
    reg signed [23:0] pcm_data=0;
    wire sck,bck,lrck,din,active_enable;
    wire [6:0] active_channel;
    wire signed [23:0] last_pcm;
    wire [31:0] received_samples,output_frames,underruns,verified_frames,serial_errors;
    always #4.069 clk=~clk;
    pcm_i2s_tx dut(.clk(clk),.rst_n(rst_n),.enable(enable),.selected_channel(selected_channel),
        .pcm_valid(pcm_valid),.pcm_channel(pcm_channel),.pcm_data(pcm_data),
        .i2s_sck(sck),.i2s_bck(bck),.i2s_lrck(lrck),.i2s_din(din),
        .active_channel(active_channel),.active_enable(active_enable),.last_pcm(last_pcm),
        .received_samples(received_samples),.output_frames(output_frames),.underruns(underruns),
        .verified_frames(verified_frames),.serial_errors(serial_errors));
    integer checks=0, cycles=0, frames_started=0, frames_decoded=0, total_frames_checked=0;
    integer last_sck=-1,last_bck=-1,last_lrck=-1,last_sck_edge=-1,last_bck_edge=-1,rx_index=0,received_expected=0;
    reg previous_lrck=1,rx_synchronized=0;
    reg [23:0] decoded=0,left_word=0,frame_expected=0,requested_expected=0;
    reg [6:0] channel_expected=0;
    reg enable_expected=0;
    integer n,target_frame,underrun_before,verified_before;
    reg [23:0] pattern;
    task check(input bit ok,input string message);
        begin checks=checks+1;if(!ok)$fatal(1,"[TB_ERROR] %s at %t",message,$time);end
    endtask
    always @(posedge clk) begin
        if(rst_n)begin
            cycles=cycles+1;
            if(enable && pcm_valid && pcm_channel==selected_channel) received_expected=received_expected+1;
        end else begin cycles=0;received_expected=0;end
    end
        always @(sck) if(rst_n)begin
        if(last_sck_edge>=0)check(cycles-last_sck_edge==5,"SCK has 50 percent duty");
        last_sck_edge=cycles;
    end
    always @(bck) if(rst_n)begin
        if(last_bck_edge>=0)check(cycles-last_bck_edge==20,"BCK has 50 percent duty");
        last_bck_edge=cycles;
    end
    always @(posedge sck) if(rst_n)begin
        if(last_sck>=0)check(cycles-last_sck==10,"SCK period = 10 audio cycles (12.288MHz)");
        last_sck=cycles;
    end
    always @(posedge bck) if(rst_n)begin
        if(last_bck>=0)check(cycles-last_bck==40,"BCK period = 40 audio cycles (3.072MHz)");
        last_bck=cycles;
        // Independent DAC-style receiver: ignore the one-bit LRCK delay,
        // shift 24 bits on BCK rising edges, and check the complete slots.
        if(lrck!=previous_lrck)begin
            previous_lrck=lrck;rx_index=0;decoded=0;
            check(din===0,"standard I2S one-bit delay is zero");
            if(!lrck)rx_synchronized=1;
        end else if(rx_synchronized)begin
            rx_index=rx_index+1;
            if(rx_index>=1 && rx_index<=24)begin
                decoded={decoded[22:0],din};
                if(rx_index==24)begin
                    if(!lrck)left_word=decoded;
                    else begin
                        check(left_word===frame_expected,"left output matches selected signed PCM");
                        check(decoded===frame_expected,"right output duplicates same frame PCM");
                    end
                end
            end else if(rx_index>=25 && rx_index<=31)check(din===0,"32-bit slot low bits padded with zero");
            if(lrck && rx_index==31)begin
                frames_decoded=frames_decoded+1;total_frames_checked=total_frames_checked+1;
                $display("[TB_DATA] I2S frame=%0d channel=%0d enabled=%0d PCM=%06h",frames_decoded,active_channel,active_enable,decoded);
            end
        end
    end
    always @(negedge lrck) if(rst_n)begin
        if(last_lrck>=0)check(cycles-last_lrck==2560,"LRCK period = 2560 audio cycles (48kHz)");
        last_lrck=cycles;
        frame_expected=requested_expected;
        frames_started=frames_started+1;
        #1;
        check(last_pcm===frame_expected,"frame snapshot is available to UART");
        check(active_channel===channel_expected && active_enable===enable_expected,"request applied at whole-frame boundary");
    end
    always @(din or lrck) if(rst_n && cycles>1)check(!bck,"DIN and LRCK change only while BCK low");
    task send_sample(input [6:0] channel,input [23:0] value);
        begin
            @(negedge clk);pcm_channel=channel;pcm_data=value;pcm_valid=1;
            @(negedge clk);pcm_valid=0;
        end
    endtask
    task run_frame(input [23:0] value,input [6:0] channel,input bit enabled);
        begin
            requested_expected=value;channel_expected=channel;enable_expected=enabled;
            target_frame=frames_started+1;
            wait(frames_started==target_frame);
            wait(frames_decoded==target_frame);
            @(negedge clk);
            check(received_samples==received_expected,"received-sample counter records matching transactions");
        end
    endtask
    task reset_module;
        begin
            @(negedge clk);rst_n=0;enable=0;pcm_valid=0;selected_channel=0;
            repeat(4)@(negedge clk);
            check(sck===0 && bck===0 && lrck===1 && din===0,"reset pins are defined");
            check(received_samples==0 && output_frames==0 && underruns==0 && serial_errors==0,"reset clears diagnostics");
            frames_started=0;frames_decoded=0;last_sck=-1;last_bck=-1;last_lrck=-1;last_sck_edge=-1;last_bck_edge=-1;
            previous_lrck=1;rx_synchronized=0;rx_index=0;decoded=0;left_word=0;
            requested_expected=0;channel_expected=0;enable_expected=0;
            rst_n=1;
        end
    endtask
    initial begin
        reset_module();
        run_frame(0,0,0);run_frame(0,0,0);
        check(underruns==0,"muted output does not report underrun");
        enable=1;
        send_sample(7,24'h654321);send_sample(0,24'h123456);
        run_frame(24'h123456,0,1);
        send_sample(0,24'h800000);run_frame(24'h800000,0,1);
        send_sample(0,24'h7fffff);run_frame(24'h7fffff,0,1);
        underrun_before=underruns;
        selected_channel=127;send_sample(0,24'h777777);
        run_frame(0,127,1);
        check(underruns==underrun_before+1,"missing newly selected channel outputs zero");
        send_sample(127,24'hffffef);run_frame(24'hffffef,127,1);
        // A -> B -> A without a fresh sample must reject the cached A sample.
        send_sample(127,24'h2468ac);
        @(negedge clk);selected_channel=0;
        repeat(2)@(negedge clk);selected_channel=127;
        run_frame(0,127,1);
        // Start a known frame, then switch during its left word. Both output
        // words must retain the old channel until the next left-frame boundary.
        send_sample(127,24'h13579b);
        requested_expected=24'h13579b;target_frame=frames_started+1;
        wait(frames_started==target_frame);
        repeat(7)@(posedge bck);
        check(active_channel==127 && last_pcm==24'h13579b,"old active frame retained before switch");
        @(negedge clk);selected_channel=0;
        send_sample(0,24'hdeadbe);
        repeat(3)@(posedge bck);
        check(active_channel==127 && last_pcm==24'h13579b,"selection does not tear the active stereo frame");
        wait(frames_decoded==target_frame);
        run_frame(24'hdeadbe,0,1);
        // Disable mid-frame; the current frame completes, following frames mute.
        send_sample(0,24'h778899);
        requested_expected=24'h778899;target_frame=frames_started+1;
        wait(frames_started==target_frame);repeat(4)@(posedge bck);
        @(negedge clk);enable=0;
        check(active_enable,"mute applies at next frame boundary");
        wait(frames_decoded==target_frame);run_frame(0,0,0);
        enable=1;run_frame(0,0,1);
                // A PCM event exactly on the left-frame boundary must be consumed once
        // immediately, rather than being lost or delayed into a stale cache.
        requested_expected=24'h102030;channel_expected=0;enable_expected=1;
        target_frame=frames_started+1;
        wait(cycles==last_bck+19);
        @(negedge clk);pcm_channel=0;pcm_data=24'h102030;pcm_valid=1;
        @(negedge clk);pcm_valid=0;
        wait(frames_decoded==target_frame);@(negedge clk);
        // Exercise every channel selector with distinct positive/negative data.
        for(n=0;n<128;n=n+1)begin
            @(negedge clk);selected_channel=n;
            pattern=(24'h812345+n*24'h010203)&24'hffffff;
            send_sample((n+1)&127,24'h112233);send_sample(n,pattern);
            run_frame(pattern,n,1);
        end
        // Corrupt only the independent receiver input for a single bit. The
        // public serial stream remains good; the digital BIST must detect it.
        send_sample(127,24'h123456);
        requested_expected=24'h123456;target_frame=frames_started+1;
        wait(frames_started==target_frame);
        repeat(3)@(negedge bck);
        if(din)force dut.monitor.din=1'b0;else force dut.monitor.din=1'b1;
        @(negedge bck);release dut.monitor.din;
        wait(frames_decoded==target_frame);repeat(3)@(negedge clk);
        check(serial_errors==1,"independent serial BIST detects a flipped bit");
        check(verified_frames>=frames_decoded-1,"serial BIST counts completed frames");
        $display("[TB_DATA] I2S counters RX=%0d frames=%0d underruns=%0d verified=%0d errors=%0d",received_samples,output_frames,underruns,verified_frames,serial_errors);
                // Assert reset inside a left word, then decode a complete new stream.
        send_sample(127,24'h765432);
        requested_expected=24'h765432;target_frame=frames_started+1;
        wait(frames_started==target_frame);repeat(5)@(posedge bck);
        reset_module();run_frame(0,0,0);
        enable=1;selected_channel=127;send_sample(127,24'hfabcde);run_frame(24'hfabcde,127,1);
        check(serial_errors==0,"receiver and output recover cleanly from reset");
        $display("[TB_INFO] Simulation Finished! frames_checked=%0d checks=%0d",total_frames_checked,checks);$finish;
    end
    initial begin #10000000;$fatal(1,"[TB_ERROR] I2S simulation timeout");end
endmodule
