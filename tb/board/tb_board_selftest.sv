`timescale 1ns/1ps
module tb_board_selftest;
    // This fixture checks BIST/network transitions, including actual startup
    // DC learning after returning to real pins. Keep its 20ms limit by using
    // 16 settled training frames; the physical board still defaults to 4096.
    localparam integer DC_LOG2=4,DC_SKIP=96,DC_WINDOW=1<<DC_LOG2;
    localparam integer REAL_FIRST_FRAME=DC_SKIP+DC_WINDOW;
    reg audio_clk=0,eth_clk=0,rx_clk=0;
    always #4.0690104167 audio_clk=~audio_clk;
    always #4 eth_clk=~eth_clk;
    always #4.017 rx_clk=~rx_clk;
    reg reset_n=0,key_n=1;
    reg [63:0] external_pdm='z;
    wire [7:0] mic_clk;
    wire [3:0] txd;
    wire [4:0] led;
    wire txc,txctl,mdc,phy_reset;
    tri1 mdio;
    reg [7:0] gmii_rxd=0;
    reg gmii_rx_dv=0;
    mems_array_pg2l200h #(.UART_ENABLE(0),.KEY_DEBOUNCE_CYCLES(8),.SELFTEST_FRAMES(32),
        .SELFTEST_TX_PACKETS(12),.STARTUP_CYCLES(1024),.DC_ESTIMATE_LOG2(DC_LOG2)) dut(
        .sys_clk_27(audio_clk),.sys_clk_125_p(eth_clk),.sys_clk_125_n(~eth_clk),
        .reset_n(reset_n),.selftest_key_n(key_n),.uart_rx(1'b1),.uart_tx(),
        .led(led),.pdm_data(external_pdm),
        .mic_clk(mic_clk),.i2s_sck(),.i2s_bck(),.i2s_lrck(),.i2s_din(),
        .PHY0_RXC(rx_clk),.PHY0_RXCTRL(1'b0),.PHY0_RXD(4'd0),
        .PHY0_TXC(txc),.PHY0_TXCTRL(txctl),.PHY0_TXD(txd),.PHY0_MDC(mdc),
        .PHY0_MDIO(mdio),.RSTN_OUT(phy_reset));
    reg [3071:0] golden[0:255];
    reg [127:0] stimulus[0:1023];
    byte unsigned tx_frame[0:1599],arp[0:63];
    integer tx_count=0,arp_count=0,udp_count=0,good_packets=0,bad_packets=0,normal_packets=0;
    integer samples=0,payload_file,checks=0,mode_changes=0,raw_period=0;
    reg was_en=0,injecting=0;
    reg [31:0] previous_epoch=0;
    reg [63:0] previous_sequence=0,previous_id=0;
    time first_udp=0,last_udp=0;
    task automatic check(input bit okay,input string detail);
        begin checks++; if(!okay)$fatal(1,"[TB_ERROR] %s time=%0t",detail,$time);end
    endtask
    task automatic press;
        begin @(negedge audio_clk);key_n=0;repeat(24)@(negedge audio_clk);
              key_n=1;repeat(24)@(negedge audio_clk);end
    endtask
    // Independent raw-input oracle for the real-mode restoration. No learned
    // DUT offset is used to decide qualification or calculate expected PCM.
    reg watch_real=0,expected_real_ready=0;
    reg [127:0] real_rails=0,expected_real_rejected=0;
    reg [3071:0] real_pcm[0:255];
    longint signed real_sum[0:127],real_half_mean[0:127];
    reg signed [31:0] real_offset[0:127];
    longint real_cycle=0,real_final_training_cycle=-1;
    integer real_frames=0,real_training_frames=0,real_pcm_checked=0,real_muted_cycles=0;
    integer real_windows=0,real_completed_training_frames=0;
    integer real_channel;
    longint signed real_mean,real_delta;
    reg [4095:0] real_raw;
    reg first_real_pcm=0,first_real_udp=0;
    reg [63:0] real_previous_id=REAL_FIRST_FRAME-1;
    function automatic longint signed mean_reference(input longint signed total,input integer shift);
        longint signed magnitude,rounded;
        begin
            magnitude=total<0?-total:total;
            rounded=(magnitude+(64'sd1<<(shift-1)))>>>shift;
            mean_reference=total<0?-rounded:rounded;
        end
    endfunction
    function automatic [23:0] real_pcm_reference(input signed [31:0] raw,
        input signed [31:0] offset);
        reg signed [32:0] corrected;
        longint signed scaled,magnitude,pcm;
        begin
            corrected=$signed({raw[31],raw})-$signed({offset[31],offset});
            // The unchanged board ROM and retained group gains are unity.
            // Preserve the parity signed33 subtraction and its sat32 boundary.
            scaled=longint'(corrected);
            if(scaled>64'sd2147483647)scaled=64'sd2147483647;
            if(scaled < -64'sd2147483648)scaled=-64'sd2147483648;
            magnitude=scaled<0?-scaled:scaled;
            pcm=(magnitude+64)>>>7;
            if(scaled<0)pcm=-pcm;
            if(pcm>8388607)pcm=8388607;
            if(pcm < -8388608)pcm=-8388608;
            real_pcm_reference=pcm[23:0];
        end
    endfunction
    always @(posedge audio_clk)begin
        real_cycle++;
        if(!watch_real || !dut.core.frontend_enable || dut.selftest_mode)begin
            real_frames=0;real_training_frames=0;expected_real_ready=0;
            real_final_training_cycle=-1;real_rails=0;expected_real_rejected=0;
            for(real_channel=0;real_channel<128;real_channel++)begin
                real_sum[real_channel]=0;real_half_mean[real_channel]=0;real_offset[real_channel]=0;
            end
        end else if(dut.core.frontend.fir2_valid)begin
            real_raw=dut.core.frontend.fir2_data;
            check(real_frames<256,"real reference storage bound");
            if(real_frames>=DC_SKIP && real_frames<REAL_FIRST_FRAME)begin
                real_training_frames++;
                for(real_channel=0;real_channel<128;real_channel++)begin
                    real_sum[real_channel]+=longint'($signed(real_raw[32*real_channel+:32]));
                    if($signed(real_raw[32*real_channel+:32])>=32'sd1073741824 ||
                       $signed(real_raw[32*real_channel+:32])<=-32'sd1073741824)
                        real_rails[real_channel]=1;
                    if(real_frames==DC_SKIP+DC_WINDOW/2-1)
                        real_half_mean[real_channel]=mean_reference(real_sum[real_channel],DC_LOG2-1);
                    if(real_frames==REAL_FIRST_FRAME-1)begin
                        real_mean=mean_reference(real_sum[real_channel],DC_LOG2);
                        real_delta=real_mean-real_half_mean[real_channel];
                        expected_real_rejected[real_channel]=real_rails[real_channel] ||
                            real_mean>64'sd33554432 || real_mean < -64'sd33554432 ||
                            real_delta>64'sd536871 || real_delta < -64'sd536871;
                        real_offset[real_channel]=expected_real_rejected[real_channel]?0:real_mean;
                    end
                end
                if(real_frames==REAL_FIRST_FRAME-1)real_final_training_cycle=real_cycle;
            end
            for(real_channel=0;real_channel<128;real_channel++)
                real_pcm[real_frames][24*real_channel+:24]=real_pcm_reference(
                    $signed(real_raw[32*real_channel+:32]),real_frames>=REAL_FIRST_FRAME?real_offset[real_channel]:32'sd0);
            real_frames++;
        end
    end
    always @(negedge audio_clk)if(watch_real && !dut.selftest_mode && dut.core.frontend_enable)begin
        if(real_final_training_cycle>=0 && real_cycle-real_final_training_cycle==131)begin
            expected_real_ready=1;
            real_windows++;real_completed_training_frames=real_training_frames;
            check(real_training_frames==DC_WINDOW,"real window uses exactly 16 settled raw frames");
            check(real_rails===128'hffffffffffffffffffffffffffffffff &&
                  expected_real_rejected===128'hffffffffffffffffffffffffffffffff,
                  "constant-low external microphones independently reject all 128 offsets");
            check(dut.core.dc_rejected===expected_real_rejected,"real restored DC rejection mask");
            $display("[TB_DATA] Real DC window=%0d..%0d frames=%0d rejected_mask=%032h first_frame=%0d",
                DC_SKIP,REAL_FIRST_FRAME-1,real_training_frames,expected_real_rejected,REAL_FIRST_FRAME);
        end
        check(dut.core.dc_ready===expected_real_ready,"real DC ready only after final channel qualification");
        check(!dut.core.frontend.parity.overrun_o,"real restoration has no parity/DC window overrun");
        if(!expected_real_ready)begin
            check(!dut.monitor_pcm_valid && !dut.core.frontend.output_fifo.valid_i && !dut.core.audio_sample_valid,
                  "real DC learning cannot escape to PCM/I2S/UDP");
            real_muted_cycles++;
        end
        if(dut.core.frontend.cal_valid)
            check(dut.core.frontend.output_fifo.valid_i===(dut.core.frontend.sample_index>=REAL_FIRST_FRAME),
                  "real FIFO releases frame112 and excludes all settling/training frames");
        if(dut.monitor_pcm_valid)begin
            check(expected_real_ready && dut.core.pcm_frame_id>=REAL_FIRST_FRAME && dut.core.pcm_frame_id<real_frames,
                  "real PCM has a completed independent training/input reference");
            if(!first_real_pcm)begin
                check(dut.core.pcm_frame_id==REAL_FIRST_FRAME && dut.monitor_pcm_channel==0,
                      "first restored PCM is frame112 channel0");
                first_real_pcm=1;
            end
            check(dut.monitor_pcm_data===real_pcm[dut.core.pcm_frame_id][24*dut.monitor_pcm_channel+:24],
                  "real PCM equals independent raw-input DC/parity/calibration arithmetic");
            real_pcm_checked++;
        end
    end
    always @(dut.selftest_mode) if(reset_n)mode_changes++;
    // Sample after NBA updates: all eight pads must track the one divider in
    // normal/BIST operation, mode changes, reset and link-loss recovery.
    integer mic_edges=0,normal_mic_periods=0;
    reg previous_mic=0;
    realtime previous_edge=0;
    always @(posedge audio_clk) begin
        #0.001;
        if($time>100) begin
            check(mic_clk === {8{dut.pdm_clock}},"Eight microphone clocks differ in phase or reset");
            check((mic_clk===8'h00)||(mic_clk===8'hff),"Unknown microphone clock output");
            if(dut.core.acquisition_active && previous_mic!==mic_clk[0]) begin
                if(previous_edge!=0)
                    check($realtime-previous_edge>162.6 && $realtime-previous_edge<162.9,
                          "PDM half-period differs from 20 audio cycles");
                previous_edge=$realtime;
                mic_edges++;
            end
            if(!dut.core.acquisition_active)previous_edge=0;
            previous_mic=mic_clk[0];
        end
    end
    // Independent PDM table index belongs to the BIST source, whose enable is
    // selftest_active. Normal listening now produces clocks before ARP, while
    // the disabled BIST source stays at period zero; those edges must not be
    // counted as BIST periods. Keep counting during corruption injection so
    // this oracle retains the source phase across the full fault scenario.
    always @(negedge dut.core.selftest_active or negedge dut.core.audio_rst_n)
        raw_period=0;
    always @(posedge mic_clk[0]) begin
        if(!dut.selftest_mode && dut.core.frontend_enable)normal_mic_periods++;
        if(dut.core.selftest_active)begin
            if(!injecting)begin
                #100;
                check(dut.core.stimulus.channel_bits===stimulus[raw_period%1024],"PDM generator channel/period mismatch");
            end
            raw_period++;
        end
    end
    function automatic [31:0] crc_step(input [31:0] old,input [7:0] b);
        reg [31:0] c;reg feedback;integer i;
        begin
            c=old;
            for(i=0;i<8;i=i+1) begin feedback=c[31]^b[i];c=c<<1;if(feedback)c=c^32'h04c11db7;end
            crc_step=c;
        end
    endfunction
    function automatic [31:0] crc_finish(input [31:0] c);
        integer i;begin for(i=0;i<32;i=i+1)crc_finish[i]=~c[31-i];end
    endfunction
    task automatic arp_reply;
        integer i;reg [31:0] c,v;
        reg [47:0] lm,pm;
        begin
            lm=48'h020000000128;pm=48'h102030405060;
            for(i=0;i<64;i=i+1)arp[i]=0;
            for(i=0;i<6;i=i+1)begin
                arp[i]=lm>>((5-i)*8);arp[6+i]=pm>>((5-i)*8);
                arp[22+i]=pm>>((5-i)*8);arp[32+i]=lm>>((5-i)*8);
            end
            arp[12]=8'h08;arp[13]=6;arp[15]=1;arp[16]=8'h08;
            arp[18]=6;arp[19]=4;arp[21]=2;
            arp[28]=192;arp[29]=168;arp[30]=10;arp[31]=1;
            arp[38]=192;arp[39]=168;arp[40]=10;arp[41]=2;
            c='1;for(i=0;i<60;i=i+1)c=crc_step(c,arp[i]);v=crc_finish(c);
            for(i=0;i<4;i=i+1)arp[60+i]=v>>(i*8);
            for(i=0;i<8;i=i+1)begin @(negedge rx_clk);gmii_rx_dv=1;gmii_rxd=(i==7)?8'hd5:8'h55;end
            for(i=0;i<64;i=i+1)begin @(negedge rx_clk);gmii_rxd=arp[i];end
            @(negedge rx_clk);gmii_rx_dv=0;
        end
    endtask
    task automatic check_frame;
        integer i,r,c,j;
        integer unsigned sum;
        reg [31:0] crc,flags,epoch;
        reg [63:0] sequence_value,id_value;
        reg [23:0] actual;
        begin
            check(tx_count>=72,"short Ethernet frame");
            for(i=0;i<7;i++)check(tx_frame[i]==8'h55,"preamble");
            check(tx_frame[7]==8'hd5,"SFD");
            crc='1;for(i=8;i<tx_count-4;i++)crc=crc_step(crc,tx_frame[i]);crc=crc_finish(crc);
            for(i=0;i<4;i++)check(tx_frame[tx_count-4+i]==((crc>>(8*i))&255),"FCS");
            if({tx_frame[20],tx_frame[21]}==16'h0806) arp_count++;
            else begin
                check(tx_count==1262,"UDP Ethernet length");
                sum=0;for(i=22;i<42;i+=2)sum+=tx_frame[i]*256+tx_frame[i+1];
                while(sum>65535)sum=(sum&65535)+(sum>>16);
                check(sum==65535,"IP checksum");
                sum=17+1216;for(i=34;i<1258;i+=2)sum+=tx_frame[i]*256+tx_frame[i+1];
                while(sum>65535)sum=(sum&65535)+(sum>>16);
                check(sum==65535,"UDP checksum");
                flags={tx_frame[78],tx_frame[79],tx_frame[80],tx_frame[81]};
                epoch={tx_frame[74],tx_frame[75],tx_frame[76],tx_frame[77]};
                sequence_value=0;for(i=0;i<8;i++)sequence_value=(sequence_value<<8)|tx_frame[66+i];
                if(flags[4])begin
                    check(dut.selftest_mode,"old self-test packet escaped after normal-mode transition");
                    if(flags[5])bad_packets++;
                    if(!injecting)begin
                        check(flags==16,"healthy BIST has error flags");
                        if(epoch!=previous_epoch)begin
                            check(sequence_value==0,"new epoch sequence not zero");previous_id=95;
                        end else check(sequence_value==previous_sequence+1,"packet sequence gap");
                        for(r=0;r<3;r++)begin
                            j=82+r*392;id_value=0;for(i=0;i<8;i++)id_value=(id_value<<8)|tx_frame[j+i];
                            check(id_value==previous_id+1,"PCM frame gap");previous_id=id_value;
                            for(c=0;c<128;c++)begin
                                actual={tx_frame[j+8+c*3+2],tx_frame[j+8+c*3+1],tx_frame[j+8+c*3]};
                                if(actual!==golden[96+(id_value%16)][24*c+:24])
                                    $fatal(1,"[TB_ERROR] BIST PCM mismatch frame=%0d channel=%0d got=%h expected=%h",id_value,c,actual,golden[96+(id_value%16)][24*c+:24]);
                                samples++;
                            end
                        end
                        if(good_packets<4 || good_packets>=22)
                            $display("[TB_DATA] packet=%0d spacing_ns=%0d",good_packets,$time-last_udp);
                        if(good_packets==2)first_udp=$time;last_udp=$time;
                        previous_epoch=epoch;previous_sequence=sequence_value;good_packets++;
                        for(i=50;i<1258;i++)$fwrite(payload_file,"%02x",tx_frame[i]);$fwrite(payload_file,"\n");
                    end
                end else begin
                    check(watch_real && expected_real_ready,"normal UDP cannot precede real DC training");
                    for(r=0;r<3;r++)begin
                        j=82+r*392;id_value=0;for(i=0;i<8;i++)id_value=(id_value<<8)|tx_frame[j+i];
                        check(id_value==real_previous_id+1,"restored real UDP starts at frame112 and remains contiguous");
                        check(id_value<real_frames,"normal UDP has independent raw reference");
                        for(c=0;c<128;c++)begin
                            actual={tx_frame[j+8+c*3+2],tx_frame[j+8+c*3+1],tx_frame[j+8+c*3]};
                            check(actual===real_pcm[id_value][24*c+:24],"normal UDP all128 PCM matches independent raw oracle");
                        end
                        real_previous_id=id_value;
                    end
                    first_real_udp=1;normal_packets++;
                end
                udp_count++;
            end
        end
    endtask
    always @(negedge eth_clk)begin
        check(!dut.tx_er,"GMII TX error");
        if(dut.tx_en)begin
            if(!was_en)tx_count=0;tx_frame[tx_count]=dut.tx_data;tx_count++;
        end else if(was_en)check_frame();
        was_en=dut.tx_en;
    end
    integer before_arp,old_good,c;
    initial begin
        $readmemh("../tb/vectors/selftest_pcm.hex",golden);
        $readmemh("../tb/vectors/selftest_pdm.hex",stimulus);
        payload_file=$fopen("../log/selftest/payloads.hex","w");check(payload_file!=0,"payload export");
        force dut.rx_data=gmii_rxd;force dut.rx_dv=gmii_rx_dv;
        repeat(10)@(negedge audio_clk);dut.clocks.test_locked=1;reset_n=1;
        wait(dut.calibration_done);repeat(8)@(negedge audio_clk);
        // Real key synchronizer/debouncer: short glitches cannot enter test.
        key_n=0;repeat(2)@(negedge audio_clk);key_n=1;repeat(20)@(negedge audio_clk);
        check(!dut.selftest_mode,"button bounce started self-test");
        press();check(dut.selftest_mode && led[1],"KEY1 failed to enter self-test");
        check(normal_mic_periods>0,"normal no-network audio did not run before BIST");
        repeat(150)@(negedge audio_clk);
        check(dut.calibration_done,"test calibration not reloaded");
        for(c=0;c<128;c++)check(dut.core.frontend.calibration.gain[c]==4194304 && dut.core.frontend.calibration.offset[c]==0,"test calibration is not unity/zero");
        check(!led[2] && !led[3] && !led[4],"pass shown without link/data");
        before_arp=arp_count;dut.phy.requested_link=1;wait(arp_count>before_arp);
        #650000;
        check(!dut.core.acquisition_active && !dut.core.overflow,"delayed initial ARP started capture");
        arp_reply();
        wait(good_packets==24);repeat(8)@(negedge audio_clk);
        check(led[2] && led[3] && !led[4],"healthy self-test LED status");
        check(dut.core.selftest_checker.checked_frames>=32,"insufficient samples for local pass");
        $display("[TB_DATA] packet interval total_ns=%0d first=%0t last=%0t",last_udp-first_udp,first_udp,last_udp);
        check(last_udp-first_udp>=1312480 && last_udp-first_udp<=1312520,"not 16000 UDP packets/second after initial buffering");
        $display("[TB_DATA] Unconnected PDM, KEY1, unity reload, 128 distinct channels, golden PCM, CRC/UDP and 16000 packet/s PASS");
        // Dropping link flushes both domains and restarts source/golden phase.
        dut.phy.requested_link=0;wait(!dut.core.acquisition_active);repeat(12)@(negedge audio_clk);
        check(!led[2] && !led[3],"link loss left stale pass LEDs");
        old_good=good_packets;before_arp=arp_count;dut.phy.requested_link=1;
        wait(arp_count>before_arp);#2000000;
        check(!dut.core.acquisition_active && !dut.core.overflow,"delayed reconnect ARP started capture");
        arp_reply();wait(good_packets>=old_good+16);
        check(!dut.selftest_fail && !led[4],"reconnected self-test mismatch");
        // Corrupt the PDM source itself, proving the checker observes the full
        // filter/calibration chain rather than a precomputed PCM bypass.
        injecting=1;force dut.core.synthetic_pdm=64'd0;
        repeat(10240)@(negedge audio_clk);release dut.core.synthetic_pdm;
        wait(dut.selftest_fail);wait(led[4]);wait(bad_packets>0);
        check(!led[2],"numeric failure retained local PASS");
        $display("[TB_DATA] PDM corruption detected; sticky fault LED and UDP selftest_error flag PASS");
        dut.phy.requested_link=0;wait(!dut.core.acquisition_active);repeat(20)@(negedge audio_clk);
        watch_real=1;external_pdm=0;
        press();repeat(150)@(negedge audio_clk);
        check(!dut.selftest_mode && !led[1] && !led[2] && !led[4],"exit failed to clear test session");
        external_pdm=0;before_arp=arp_count;dut.phy.requested_link=1;
        wait(arp_count>before_arp);arp_reply();wait(normal_packets>0);
        check(expected_real_ready && first_real_pcm && first_real_udp && real_pcm_checked>=128 && real_muted_cycles>0,
              "real mode restoration covers completed learning, muted startup and all128 first PCM");
        check(dut.core.frontend.capture.bits_o===128'd0,"normal mode did not select external microphone pins");
        dut.phy.requested_link=0;repeat(20)@(negedge audio_clk);
        press();repeat(150)@(negedge audio_clk);check(dut.selftest_mode,"second self-test press");
        reset_n=0;repeat(10)@(negedge audio_clk);
        check(!dut.selftest_mode && led==0,"global reset LED/mode defaults");
        $fclose(payload_file);
        $display("[TB_DATA] Link restart, mode exit, external source restoration and reset PASS");
        $display("[TB_INFO] BIST good_packets=%0d bad_packets=%0d PCM_exact=%0d checks=%0d mode_changes=%0d normal_mic_periods=%0d",good_packets,bad_packets,samples,checks,mode_changes,normal_mic_periods);
        check(real_windows==1 && real_completed_training_frames==DC_WINDOW,"one actual real restoration training window completed");
        $display("[TB_INFO] BIST real_DC_windows=%0d real_DC_window=%0d real_first_frame=%0d real_training_frames=%0d real_PCM_exact=%0d real_muted_cycles=%0d",
            real_windows,DC_WINDOW,REAL_FIRST_FRAME,real_completed_training_frames,real_pcm_checked,real_muted_cycles);
        $display("[TB_INFO] Simulation Finished!");$finish;
    end
    initial begin #20000000;$fatal(1,"[TB_ERROR] BIST timeout");end
endmodule
