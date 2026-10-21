`timescale 1ns/1ps
// Real board/core/PDM/filter/parity/calibration/I2S/UART integration.
// PHY link and physical PLL/DDR wrappers are stubs; ARP parsing stays real.
module tb_board_audio;
    reg ref_clk=0,eth_clk=0,rx_clk=0,reset_n=0,uart_rx=1;
    always #18.5185185 ref_clk=~ref_clk;
    always #4 eth_clk=~eth_clk;
    always #4.017 rx_clk=~rx_clk;
    wire audio_clk=dut.audio_clk;
    wire uart_tx,sck,bck,lrck,din;
    wire [7:0] mic_clk;
    wire [63:0] external_pdm;
    tri1 mdio;
    reg [7:0] host_rxd=0;
    reg host_dv=0;
    integer model_id=0;
    localparam integer DC_LOG2=7,DC_SKIP=96,DC_WINDOW=1<<DC_LOG2;
    localparam integer REAL_FIRST_FRAME=DC_SKIP+DC_WINDOW;
    // The external microphone profile is quiet through learning, then carries
    // real AC. The core's original built-in PDM/BIST source is untouched.
    board_dc_microphone_source microphones(.clk(audio_clk),.rst_n(dut.audio_rst_n),
        .enable(dut.calibration_done && !dut.selftest_mode),.mic_clk(mic_clk[0]),
        .step_enable(model_id>=DC_SKIP),.tone_enable(model_id>=REAL_FIRST_FRAME),
        .pdm_data(external_pdm));
    mems_array_pg2l200h #(.KEY_DEBOUNCE_CYCLES(8),.SELFTEST_FRAMES(16),.SELFTEST_TX_PACKETS(4),
        .STARTUP_CYCLES(1024),.DC_ESTIMATE_LOG2(DC_LOG2),
        .UART_DIV(8),.UART_REPORT_CYCLES(27000),.UART_MS_CYCLES(27000),
        .UART_RESET_CYCLES(32400),.UART_MODE_CYCLES(2700),.UART_WINDOW_CYCLES(2700),.UART_PRESCALE_BITS(6)) dut(
        .sys_clk_27(ref_clk),.sys_clk_125_p(eth_clk),.sys_clk_125_n(~eth_clk),.reset_n(reset_n),
        .selftest_key_n(1'b1),.uart_rx(uart_rx),.uart_tx(uart_tx),.pdm_data(external_pdm),.mic_clk(mic_clk),.led(),
        .i2s_sck(sck),.i2s_bck(bck),.i2s_lrck(lrck),.i2s_din(din),
        .PHY0_RXC(rx_clk),.PHY0_RXCTRL(1'b0),.PHY0_RXD(4'b0),.PHY0_TXC(),.PHY0_TXCTRL(),.PHY0_TXD(),
        .PHY0_MDC(),.PHY0_MDIO(mdio),.RSTN_OUT());
    integer checks=0,pcm_checked=0,serial_frames=0,nonzero_frames=0;
    integer i2s_lines=0,gain_lines=0,sys_lines=0,raw_file;
    reg [3071:0] golden[0:4095];
    reg [31:0] iwords[0:13],gwords[0:13],swords[0:33];
    longint signed dc_sum[0:127],dc_first_half[0:127];
    reg signed [31:0] expected_offset[0:127];
    reg [127:0] raw_rail_seen=0,expected_rejected=0,expected_status_rejected=0;
    reg expected_dc_ready=0,oracle_window_fault=0,model_active=0;
    longint audio_cycle=0,next_capture_cycle=0,final_training_cycle=-1;
    longint signed full_mean,half_mean,difference;
    integer dc_windows=0,real_generations=0,bist_generations=0,dc_accepted=0,dc_rejected=0;
    integer sys_training=0,sys_ready=0,sys_rejected=0,sys_bist=0,training_muted=0;
    integer serial_channel_frames[0:127];
    reg [31:0] expected_audio_before_edge=0;
    task automatic check(input bit ok,input string text);
        begin checks++;if(!ok)$fatal(1,"[TB_ERROR] %s time=%0t",text,$time);end
    endtask
    function automatic longint signed mean_reference(input longint signed total,input integer shift);
        longint signed magnitude,rounded;
        begin
            magnitude=total<0?-total:total;
            rounded=(magnitude+(64'sd1<<(shift-1)))>>>shift;
            mean_reference=total<0?-rounded:rounded;
        end
    endfunction
    function automatic [23:0] pcm_reference(input signed [31:0] value,
        input signed [31:0] offset,input [23:0] gain);
        reg signed [32:0] corrected;
        longint signed product,scaled,magnitude,pcm;
        begin
            // Preserve the complete signed33 subtraction before multiplication.
            corrected=$signed({value[31],value})-$signed({offset[31],offset});
            product=longint'(corrected)*$signed({1'b0,gain});
            magnitude=product<0?-product:product;
            scaled=(magnitude+64'sd2097152)>>>22;
            if(product<0)scaled=-scaled;
            if(scaled>64'sd2147483647)scaled=64'sd2147483647;
            if(scaled < -64'sd2147483648)scaled=-64'sd2147483648;
            // Board per-channel ROM is unity/zero in this integration test.
            magnitude=scaled<0?-scaled:scaled;
            pcm=(magnitude+64)>>>7;
            if(scaled<0)pcm=-pcm;
            if(pcm>8388607)pcm=8388607;
            if(pcm < -8388608)pcm=-8388608;
            pcm_reference=pcm[23:0];
        end
    endfunction
    integer channel;
    reg [4095:0] raw_frame;
    reg [23:0] oracle_even,oracle_odd;
    always @(posedge audio_clk) begin
        audio_cycle++;
        if(!dut.core.audio_rst_n)check(!dut.audio_gain_cfg_ready,"parity cfg_ready cannot acknowledge during core reset");
        if(!dut.core.frontend_enable)begin
            model_id=0;model_active=0;expected_dc_ready=0;oracle_window_fault=0;
            raw_rail_seen=0;expected_rejected=0;expected_status_rejected=0;
            final_training_cycle=-1;next_capture_cycle=0;
            for(channel=0;channel<128;channel++)begin
                dc_sum[channel]=0;dc_first_half[channel]=0;expected_offset[channel]=0;
            end
        end else begin
            if(!model_active)begin
                model_active=1;
                if(dut.selftest_mode)bist_generations++;else real_generations++;
            end
            if(dut.core.frontend.fir2_valid)begin
            raw_frame=dut.core.frontend.fir2_data;
            // The independent schedule has CHANNELS+3 pipeline cycles and a
            // non-overlapping acceptance edge. A lost frame poisons learning.
            if(audio_cycle<next_capture_cycle)begin
                if(!dut.selftest_mode && !expected_dc_ready)oracle_window_fault=1;
                check(0,"unexpected board FIR-to-parity overrun; real window cannot be qualified");
            end
            next_capture_cycle=audio_cycle+132;
            if(!dut.selftest_mode && model_id>=DC_SKIP && model_id<REAL_FIRST_FRAME)begin
                for(channel=0;channel<128;channel++)begin
                    dc_sum[channel]+=longint'($signed(raw_frame[channel*32 +: 32]));
                    if($signed(raw_frame[channel*32 +: 32])>=32'sd1073741824 ||
                       $signed(raw_frame[channel*32 +: 32])<=-32'sd1073741824)
                        raw_rail_seen[channel]=1;
                    if(model_id==DC_SKIP+DC_WINDOW/2-1)
                        dc_first_half[channel]=mean_reference(dc_sum[channel],DC_LOG2-1);
                    if(model_id==REAL_FIRST_FRAME-1)begin
                        full_mean=mean_reference(dc_sum[channel],DC_LOG2);
                        half_mean=dc_first_half[channel];difference=full_mean-half_mean;
                        expected_rejected[channel]=raw_rail_seen[channel] || oracle_window_fault ||
                            full_mean>64'sd33554432 || full_mean < -64'sd33554432 ||
                            difference>64'sd536871 || difference < -64'sd536871;
                        expected_offset[channel]=expected_rejected[channel]?32'sd0:full_mean;
                    end
                end
                if(model_id==REAL_FIRST_FRAME-1)final_training_cycle=audio_cycle;
            end
            // Active configuration commits on this accepted frame edge. Read
            // its public status after NBA; arithmetic itself is independent.
            #1;
            oracle_even=dut.selftest_mode?24'h400000:dut.parity_active_even_gain;
            oracle_odd=dut.selftest_mode?24'h400000:dut.parity_active_odd_gain;
            check(model_id<4096,"golden frame storage bound");
            for(channel=0;channel<128;channel++)
                golden[model_id][channel*24 +: 24]=pcm_reference($signed(raw_frame[channel*32 +: 32]),
                    (!dut.selftest_mode && model_id>=REAL_FIRST_FRAME)?expected_offset[channel]:32'sd0,
                    channel[0]?oracle_odd:oracle_even);
            model_id++;
            end
        end
    end
    // DC flags/rejected bits have their own independently scheduled oracle;
    // no learned DUT offset is ever used in the expected PCM calculation.
    integer rejection_channel;
    // Ignore only the simulator's initial X-to0 clock assignment before the
    // first synchronous reset edge; every subsequent audio cycle is checked.
    always @(negedge audio_clk)if(audio_cycle>0)begin
        if(dut.core.frontend_enable && !dut.selftest_mode && final_training_cycle>=0)begin
            // Sum, mean and qualification run beside the audio pipe; the
            // rejection/state write is aligned with that channel's product.
            if(audio_cycle-final_training_cycle>=4 && audio_cycle-final_training_cycle<=131)begin
                rejection_channel=audio_cycle-final_training_cycle-4;
                expected_status_rejected[rejection_channel]=expected_rejected[rejection_channel];
            end
            if(audio_cycle-final_training_cycle==131)begin
                expected_dc_ready=1;dc_windows++;
                for(rejection_channel=0;rejection_channel<128;rejection_channel++)begin
                    if(expected_rejected[rejection_channel])dc_rejected++;
                    else dc_accepted++;
                end
                check(!expected_rejected[0] && !expected_rejected[1],"quiet small positive/negative DC accepted");
                check(expected_rejected[2] && expected_rejected[3],"constant-low microphone pair rejected");
                check(expected_rejected[4],"large DC microphone rejected");
                check(expected_rejected[5],"window step rejected by independent raw stability estimate");
                check(expected_offset[0]<0 && expected_offset[1]<0 && expected_offset[3]==0 && expected_offset[8]>0,
                    "independent signed offsets and zero rejected offset");
                $display("[TB_DATA] Startup DC generation=%0d raw_window=%0d..%0d accepted=%0d rejected_mask=%032h",real_generations,DC_SKIP,REAL_FIRST_FRAME-1,dc_accepted,expected_rejected);
            end
        end
        check(dut.core.dc_ready===expected_dc_ready,"DC ready follows final trained-frame pipeline completion");
        check(dut.core.dc_rejected===expected_status_rejected,"per-channel rejection mask matches independent training oracle");
        if(dut.audio_rst_n)begin
            check(dut.board_audio_debug[12]===1'b1 && dut.board_audio_debug[13]===expected_dc_ready &&
                  dut.board_audio_debug[14]===|expected_status_rejected,"board packed DC flags12..14");
            check(dut.board_audio_debug[9]===dut.audio_rst_n && dut.board_audio_debug[10]===dut.calibration_done &&
                  dut.board_audio_debug[11]===dut.loaded_mode && dut.board_audio_debug[19]===dut.led[0],
                  "existing board reset/ROM/mode/heartbeat flags remain correctly placed");
        end
        if(dut.core.frontend_enable && !dut.selftest_mode && !expected_dc_ready)begin
            check(!dut.monitor_pcm_valid && !dut.core.frontend.output_fifo.valid_i && !dut.core.audio_sample_valid,
                  "learning window cannot reach PCM/I2S/UDP");
            // An already-started I2S stereo frame finishes without truncation
            // during a mode transition. By the second raw frame it has drained.
            if(model_id>=2)check(dut.i2s_last_pcm==0,"training I2S remains silent after prior stereo frame drains");
            training_muted++;
        end
        if(dut.core.frontend.cal_valid)begin
            check(dut.core.frontend.output_fifo.valid_i===
                (dut.core.frontend.sample_index>=(dut.selftest_mode?DC_SKIP:REAL_FIRST_FRAME)),
                "FIFO releases BIST96 or first fully corrected real frame224");
        end
        // Source CDC captures pre-edge values. Keep the expected pre-edge DC
        // state separate from the oracle's blocking clear on the next posedge.
        expected_audio_before_edge=0;
        if(dut.audio_rst_n)begin
            expected_audio_before_edge[9]=1;
            expected_audio_before_edge[10]=dut.calibration_done;
            expected_audio_before_edge[11]=dut.loaded_mode;
            expected_audio_before_edge[12]=1;
            expected_audio_before_edge[13]=expected_dc_ready;
            expected_audio_before_edge[14]=|expected_status_rejected;
            expected_audio_before_edge[19]=dut.led[0];
        end
    end
    // This checks every accepted calibrated PCM, before any I2S selection.
    always @(negedge audio_clk) if(dut.monitor_pcm_valid)begin
        check(dut.core.pcm_frame_id>=(dut.selftest_mode?DC_SKIP:REAL_FIRST_FRAME),"PCM excludes settled/training frames");
        check(dut.core.pcm_frame_id<model_id,"PCM frame has an independent input reference");
        check(dut.monitor_pcm_data===golden[dut.core.pcm_frame_id][dut.monitor_pcm_channel*24 +: 24],$sformatf("actual PCM frame=%0d channel=%0d got=%06h expected=%06h model_id=%0d gains=%06h/%06h",dut.core.pcm_frame_id,dut.monitor_pcm_channel,dut.monitor_pcm_data,golden[dut.core.pcm_frame_id][dut.monitor_pcm_channel*24 +: 24],model_id,dut.parity_active_even_gain,dut.parity_active_odd_gain));
        pcm_checked++;
    end
    reg cache_valid=0;
    reg [23:0] cache_pcm=0,frame_sample=0,decoded=0,left_pcm=0;
    reg [6:0] observed_channel=0;
    reg observed_enable=0,previous_lrck=1,serial_synchronized=0;
    integer serial_index=0;
    always @(posedge audio_clk)begin
        if(!dut.audio_rst_n)begin cache_valid=0;observed_channel=0;observed_enable=0;end
        else begin
            if(dut.audio_i2s_channel!=observed_channel || (dut.audio_i2s_enable && dut.acquisition_run)!=observed_enable)cache_valid=0;
            observed_channel=dut.audio_i2s_channel;observed_enable=dut.audio_i2s_enable && dut.acquisition_run;
            if(observed_enable && dut.monitor_pcm_valid && dut.monitor_pcm_channel==observed_channel)begin
                cache_valid=1;cache_pcm=dut.monitor_pcm_data;
            end
        end
    end
    always @(negedge dut.audio_rst_n)begin previous_lrck=1;serial_synchronized=0;serial_index=0;end
    always @(negedge lrck) if(dut.audio_rst_n)begin
        frame_sample=observed_enable && cache_valid?cache_pcm:24'b0;cache_valid=0;
        #1;
        check(dut.i2s_last_pcm===frame_sample,"board I2S frame uses accepted PCM from selected channel");
    end
    always @(posedge bck) if(dut.audio_rst_n)begin
        if(lrck!=previous_lrck)begin
            previous_lrck=lrck;serial_index=0;decoded=0;
            check(din===0,"board standard I2S delay bit");
            if(!lrck)serial_synchronized=1;
        end else if(serial_synchronized)begin
            serial_index++;
            if(serial_index<=24)begin
                decoded={decoded[22:0],din};
                if(serial_index==24)begin
                    if(!lrck)left_pcm=decoded;
                    else begin
                        check(left_pcm===frame_sample && decoded===frame_sample,"board pin I2S stereo decode matches selected real PCM");
                        serial_frames++;if(decoded!=0)nonzero_frames++;
                        if(observed_enable && !dut.selftest_mode && expected_dc_ready)
                            serial_channel_frames[observed_channel]++;
                    end
                end
            end else check(din===0,"board I2S unused slot bits zero");
        end
    end
    task automatic send_byte(input byte value);
        integer bitn;
        begin
            @(negedge ref_clk);uart_rx=0;repeat(8)@(negedge ref_clk);
            for(bitn=0;bitn<8;bitn++)begin uart_rx=value[bitn];repeat(8)@(negedge ref_clk);end
            uart_rx=1;repeat(12)@(negedge ref_clk);
        end
    endtask
    task automatic send_line(input string value);
        integer index;begin for(index=0;index<value.len();index++)send_byte(value.getc(index));end
    endtask
    // Capture expected flags on the real CDC source handshake, then bind that
    // expectation to the SYS3 sequence at report collection. A line may finish
    // after a mode/reset change; comparing it with a newer live state is wrong.
    reg [31:0] expected_audio_held=0;
    reg [31:0] expected_sys_flags[0:1023];
    reg expected_sys_fresh[0:1023];
    integer expected_sys_index;
    always @(posedge audio_clk)begin
        if(dut.g_uart.diagnostics.audio_bridge.src_rst_n &&
           dut.g_uart.diagnostics.audio_bridge.request_sync!=dut.g_uart.diagnostics.audio_bridge.acknowledge)begin
            expected_audio_held=dut.audio_rst_n?expected_audio_before_edge:32'b0;
        end
    end
    always @(posedge ref_clk)begin
        if(dut.g_uart.diagnostics.report.rst_n && dut.g_uart.diagnostics.report.collecting &&
           dut.g_uart.diagnostics.report.wait_count==0)begin
            expected_sys_index=dut.g_uart.diagnostics.report.sequence_count;
            check(expected_sys_index<1024,"SYS3 expected snapshot storage bound");
            expected_sys_flags[expected_sys_index]=expected_audio_held;
            expected_sys_fresh[expected_sys_index]=dut.g_uart.diagnostics.fresh[0];
        end
    end
    string line="",token;
    byte received_byte;
    integer bitn,wordn,base,parsed;
    reg [31:0] parsed_word;
    initial forever begin
        @(negedge uart_tx);repeat(4)@(posedge ref_clk);check(uart_tx===0,"board UART start");
        for(bitn=0;bitn<8;bitn++)begin repeat(8)@(posedge ref_clk);received_byte[bitn]=uart_tx;end
        repeat(8)@(posedge ref_clk);check(uart_tx===1,"board UART stop");
        if(received_byte==10)begin
            if(line.substr(0,4)=="SYS3 ")begin
                check(line.len()==311,"independent audio replies preserve SYS3 frame length");
                for(wordn=0;wordn<34;wordn++)begin
                    token=line.substr(5+9*wordn,5+9*wordn+7);
                    parsed=$sscanf(token,"%h",parsed_word);
                    check(parsed==1 && !$isunknown(parsed_word),"defined SYS3 word");swords[wordn]=parsed_word;
                end
                check(swords[0]<1024,"SYS3 sequence bounds");
                check(swords[7][0]===expected_sys_fresh[swords[0]],"SYS3 audio freshness matches recorded snapshot");
                if(swords[7][0])begin
                    check((swords[8]&32'h00087e00)===(expected_sys_flags[swords[0]]&32'h00087e00),
                        "SYS3 word8 reports independent DC ready/rejected and original reset/ROM/mode/heartbeat bits");
                    check(swords[8][18:15]==0,"DC flags do not alter reserved SYS3 bits15..18");
                    if(swords[8][9] && swords[8][12] && !swords[8][13])sys_training++;
                    if(swords[8][13])sys_ready++;
                    if(swords[8][14])sys_rejected++;
                    if(swords[8][11])sys_bist++;
                end
                sys_lines++;
            end else begin
                base=line.substr(0,4)=="I2S1 "?5:6;
                check(base==5 || line.substr(0,5)=="GAIN1 ","independent audio frame identifier");
                check(line.len()==base+126,"independent audio frame complete length");
                for(wordn=0;wordn<14;wordn++)begin
                    token=line.substr(base+9*wordn,base+9*wordn+7);
                    parsed=$sscanf(token,"%h",parsed_word);check(parsed==1 && !$isunknown(parsed_word),"defined audio UART word");
                    if(base==5)iwords[wordn]=parsed_word;else gwords[wordn]=parsed_word;
                end
                if(base==5)i2s_lines++;else gain_lines++;
            end
            check(line.getc(line.len()-1)==13,"UART frame ends in CRLF");
            $fwrite(raw_file,"%s\n",line);line="";
        end else line={line,received_byte};
    end
    task automatic learn_peer;
        reg [7:0] arp[0:63];reg [31:0] crc;reg [47:0] local_mac,peer_mac;
        integer i,k;
        begin
            local_mac=48'h020000000128;peer_mac=48'h102030405060;
            for(i=0;i<64;i++)arp[i]=0;
            for(i=0;i<6;i++)begin
                arp[i]=local_mac>>((5-i)*8);arp[6+i]=peer_mac>>((5-i)*8);
                arp[22+i]=peer_mac>>((5-i)*8);arp[32+i]=local_mac>>((5-i)*8);
            end
            arp[12]=8'h08;arp[13]=6;arp[15]=1;arp[16]=8'h08;arp[18]=6;arp[19]=4;arp[21]=2;
            arp[28]=192;arp[29]=168;arp[30]=10;arp[31]=1;
            arp[38]=192;arp[39]=168;arp[40]=10;arp[41]=2;
            crc='1;
            for(i=0;i<60;i++)begin crc=crc^arp[i];for(k=0;k<8;k++)crc=crc[0]?(crc>>1)^32'hedb88320:crc>>1;end
            crc=~crc;for(i=0;i<4;i++)arp[60+i]=crc>>(8*i);
            for(i=0;i<8;i++)begin @(negedge rx_clk);host_dv=1;host_rxd=i==7?8'hd5:8'h55;end
            for(i=0;i<64;i++)begin @(negedge rx_clk);host_rxd=arp[i];end
            @(negedge rx_clk);host_dv=0;
        end
    endtask
    integer prior_reply,prior_pcm,prior_nonzero,prior_frames,c,prior_dc_windows,prior_generations;
    reg [127:0] frozen_rejected;
    reg signed [31:0] frozen_offsets[0:127];
    initial begin
        for(c=0;c<128;c++)serial_channel_frames[c]=0;
        for(c=0;c<1024;c++)begin expected_sys_flags[c]=0;expected_sys_fresh[c]=0;end
        raw_file=$fopen("../log/board_audio/rtl_uart.log","w");check(raw_file!=0,"board audio UART log opened");
        force dut.rx_data=host_rxd;force dut.rx_dv=host_dv;
        repeat(10)@(negedge ref_clk);reset_n=1;wait(dut.calibration_done);
        for(c=0;c<128;c++)check(dut.core.frontend.calibration.gain[c]==4194304 && dut.core.frontend.calibration.offset[c]==0,"test board calibration ROM unity/zero");
        prior_reply=i2s_lines;send_line("@I2S=0\n");wait(i2s_lines>prior_reply);
        wait(dut.i2s_active_enable && dut.i2s_active_channel==0);
        wait(pcm_checked>1280 && nonzero_frames>=8);
        check(expected_dc_ready && dc_windows==1 && dc_accepted>0 && dc_rejected>=4,
            "first real startup learns valid offsets and safely rejects abnormal microphones");
        check(!dut.link_up && !dut.core.peer_ready && !dut.core.acquisition_active,"real audio runs before PHY link or ARP");
        check(dut.core.frontend_enable && dut.i2s_received_samples>0,"no-network PCM reaches active I2S");
        prior_reply=i2s_lines;send_line("@I2S?\n");wait(i2s_lines>prior_reply);
        check(iwords[1][0] && iwords[3][7] && iwords[3][6:0]==0 && iwords[8]>0 && iwords[12]>0 && iwords[13]==0,"fresh independent I2S query reports real activity");
        $display("[TB_DATA] No-link/no-ARP real PDM -> FIR -> calibration -> nonzero I2S PASS");
        prior_reply=gain_lines;send_line("@GAIN=200000,600000\n");wait(gain_lines>prior_reply);
        wait(dut.parity_active_even_gain==24'h200000 && dut.parity_active_odd_gain==24'h600000);
        prior_pcm=pcm_checked;wait(pcm_checked>prior_pcm+2560);
        prior_reply=gain_lines;send_line("@GAIN?\n");wait(gain_lines>prior_reply);
        check(gwords[1][0] && gwords[6][23:0]==24'h200000 && gwords[7][23:0]==24'h600000,"UART query confirms applied parity gains");
        prior_reply=i2s_lines;send_line("@I2S=1\n");wait(i2s_lines>prior_reply);wait(dut.i2s_active_channel==1);
        prior_nonzero=nonzero_frames;wait(nonzero_frames>=prior_nonzero+8);
        prior_reply=i2s_lines;send_line("@I2S=127\n");wait(i2s_lines>prior_reply);wait(dut.i2s_active_channel==127);
        prior_nonzero=nonzero_frames;wait(nonzero_frames>=prior_nonzero+8);
        check(!dut.core.processing_error && !dut.core.overflow && !dut.i2s_serial_errors,"real parity-configured audio remains healthy");
        $display("[TB_DATA] Applied odd/even gains and real PCM arithmetic for all128 channels; I2S 0 -> 1 -> 127 PASS");
        // Enable network only for the original independent digital BIST oracle.
        dut.phy.requested_link=1;wait(dut.link_up);wait(dut.core.network.u_arp_rx.link_sync);learn_peer();wait(dut.core.peer_ready);
        send_byte("t");wait(dut.selftest_mode);wait(dut.selftest_pass && dut.selftest_tx_pass);
        check(dut.parity_active_even_gain==24'h200000 && dut.parity_active_odd_gain==24'h600000,"BIST retains installed acoustic gains");
        check(dut.core.frontend.parity.frame_even==24'h400000 && dut.core.frontend.parity.frame_odd==24'h400000,"BIST applies unity parity bypass");
        check(!expected_dc_ready && dut.core.dc_rejected==0 && !dut.core.frontend.parity.frame_dc_train,
            "original BIST bypasses startup training and all learned DC offsets");
        check(!dut.selftest_fail && !dut.i2s_serial_errors,"BIST PCM reaches I2S without corruption");
        prior_reply=sys_lines;send_byte("?");wait(sys_lines>prior_reply && sys_bist>0);
        send_byte("t");wait(!dut.selftest_mode);wait(dut.calibration_done);
        wait(dut.core.frontend.parity.frame_even==24'h200000 && dut.core.frontend.parity.frame_odd==24'h600000);
        check(!expected_dc_ready,"leaving BIST requires a new real DC training window");
        wait(expected_dc_ready);check(dc_windows==2 && real_generations>=2,"mode switch completes fresh independent DC training");
        prior_dc_windows=dc_windows;prior_generations=real_generations;frozen_rejected=expected_rejected;
        for(c=0;c<128;c++)frozen_offsets[c]=expected_offset[c];
        dut.phy.requested_link=0;wait(!dut.link_up);
        prior_nonzero=nonzero_frames;prior_pcm=pcm_checked;wait(nonzero_frames>=prior_nonzero+8 && pcm_checked>prior_pcm+1280);
        check(!dut.core.acquisition_active && dut.core.frontend_enable,"disconnect flushes network while keeping real I2S running");
        check(dc_windows==prior_dc_windows && real_generations==prior_generations && expected_dc_ready &&
              expected_rejected===frozen_rejected,"link loss does not restart or change DC learning");
        for(c=0;c<128;c++)check(expected_offset[c]===frozen_offsets[c],"link loss preserves independent frozen DC offset");
        // Exercise the real board reset instead of forcing any pipeline state.
        prior_dc_windows=dc_windows;prior_generations=real_generations;
        @(negedge ref_clk);reset_n=0;repeat(20)@(negedge ref_clk);
        check(!dut.audio_rst_n && !expected_dc_ready && model_id==0,"physical reset clears DC ready and training history");
        reset_n=1;wait(dut.calibration_done);wait(expected_dc_ready);
        check(dc_windows==prior_dc_windows+1 && real_generations==prior_generations+1,
            "physical reset performs exactly one new real training window");
        wait(dut.parity_active_even_gain==24'h200000 && dut.parity_active_odd_gain==24'h600000);
        prior_nonzero=nonzero_frames;wait(nonzero_frames>=prior_nonzero+8);
        prior_reply=i2s_lines;send_line("@I2S=OFF\n");wait(i2s_lines>prior_reply);wait(!dut.i2s_active_enable);
        repeat(2)@(negedge lrck);check(dut.i2s_last_pcm==0,"UART OFF mutes complete stereo frames");
        check(sys_lines>0 && gain_lines>=2 && i2s_lines>=5,"SYS3 and both independent audio frame types coexist");
        check(sys_training>0 && sys_ready>0 && sys_rejected>0 && sys_bist>0,
            "serialized SYS3 covers training/completed/rejected/BIST states");
        check(serial_channel_frames[0]>0 && serial_channel_frames[1]>0 && serial_channel_frames[127]>0,
            "selected real I2S channels0/1/127 decoded after DC correction");
        check(training_muted>0 && dc_windows==3 && dc_accepted>0 && dc_rejected>=12,
            "initial boot, real-mode restoration and reset all enforce qualified/muted startup windows");
        check(dut.i2s_serial_errors==0,"independent hardware serial monitor reports zero errors");
        $fclose(raw_file);
        $display("[TB_INFO] Board audio PCM_checked=%0d serial_frames=%0d nonzero_frames=%0d SYS3=%0d I2S1=%0d GAIN1=%0d checks=%0d",pcm_checked,serial_frames,nonzero_frames,sys_lines,i2s_lines,gain_lines,checks);
        $display("[TB_INFO] Board DC windows=%0d accepted=%0d rejected=%0d muted_cycles=%0d SYS3_training=%0d ready=%0d rejected=%0d BIST=%0d",dc_windows,dc_accepted,dc_rejected,training_muted,sys_training,sys_ready,sys_rejected,sys_bist);
        $display("[TB_INFO] Simulation Finished!");$finish;
    end
    initial begin #40000000;$fatal(1,"[TB_ERROR] board audio integration timeout");end
endmodule

// Test-only electrical PDM stimulus: no DUT state or data is forced. Each
// threshold is held through bit-reversed 256-period pulse-density cycles.
module board_dc_microphone_source(input wire clk,rst_n,enable,mic_clk,step_enable,tone_enable,
    output wire [63:0] pdm_data);
    reg mic_previous;
    reg [9:0] period_index;
    reg [127:0] channel_bits;
    wire [7:0] reversed_index={period_index[0],period_index[1],period_index[2],period_index[3],
                              period_index[4],period_index[5],period_index[6],period_index[7]};
    integer c,threshold;
    reg [1:0] phase_group;
    always @(posedge clk)begin
        if(!rst_n || !enable)begin mic_previous<=0;period_index<=0;channel_bits<=0;end
        else begin
            mic_previous<=mic_clk;
            if(mic_clk && !mic_previous)begin
                for(c=0;c<128;c++)begin
                    threshold=128+(c%5)-2;
                    if(c==2 || c==3)threshold=0;
                    else if(c==4)threshold=144;
                    else if(c==5)threshold=step_enable?130:126;
                    if(tone_enable && c!=2 && c!=3)begin
                        phase_group=period_index[9:8]+(c%4);
                        threshold=threshold+(phase_group[1]?12:-12);
                    end
                    channel_bits[c]<=reversed_index<threshold;
                end
                period_index<=period_index+1'b1;
            end
        end
    end
    genvar k;
    generate for(k=0;k<64;k++)begin:slots
        assign pdm_data[k]=mic_clk?channel_bits[2*k+1]:channel_bits[2*k];
    end endgenerate
endmodule

module pango_board_clocks(input wire ref_clk_27,ref_clk_125_p,ref_clk_125_n,rst_n,
    output wire audio_clk,eth_clk,locked,monitor_ref_clk,monitor_raw125_clk,monitor_clk96,
    output wire [2:0] monitor_locks);
    reg a=0,b=0;always #4.0690104167 a=~a;always #5.2083333333 b=~b;
    assign audio_clk=a;assign eth_clk=ref_clk_125_p;assign locked=rst_n;
    assign monitor_ref_clk=ref_clk_27;assign monitor_raw125_clk=ref_clk_125_p;
    assign monitor_clk96=b;assign monitor_locks={3{rst_n}};
endmodule
module GTP_DFF #(parameter GRS_EN="TRUE",parameter INIT=1'b0)(input wire CLK,D,output reg Q=INIT);
    always @(posedge CLK)Q<=D;
endmodule
module pango_rgmii_io(input wire tx_clk,rst_n,input wire [7:0] tx_data,
    input wire tx_en,tx_er,rgmii_rxc,rgmii_rx_ctl,input wire [3:0] rgmii_rxd,
    output wire rx_clk,output wire [7:0] rx_data,output wire rx_dv,rx_er,
    output wire rgmii_txc,rgmii_tx_ctl,output wire [3:0] rgmii_txd);
    assign rx_clk=rgmii_rxc;assign rx_data=0;assign rx_dv=0;assign rx_er=0;
    assign rgmii_txc=tx_clk;assign rgmii_tx_ctl=tx_en;assign rgmii_txd=tx_data[3:0];
endmodule
module rtl8211f_manager(input wire clk,rst_n,mdio_in,
    output wire phy_rst_n,mdc,mdio_out,mdio_oe,ready,link_up,fault,
    output wire [4:0] phy_address,output wire [287:0] debug_status);
    reg requested_link=0;
    assign phy_rst_n=rst_n;assign mdc=0;assign mdio_out=1;assign mdio_oe=0;
    assign ready=rst_n;assign link_up=rst_n && requested_link;assign fault=0;
    assign phy_address=5;assign debug_status=0;
endmodule
