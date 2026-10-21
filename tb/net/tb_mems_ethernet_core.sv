`timescale 1ns/1ps
module tb_mems_ethernet_core;
    localparam integer N=16384,STARTUP=8;
    reg audio_clk=0,eth_clk=0,rx_clk=0;
    always #4.0690104167 audio_clk=~audio_clk;
    always #4 eth_clk=~eth_clk;
    always #4.017 rx_clk=~rx_clk;
    reg rst_n=0,run=0,link_up=0,cfg_valid=0;
    reg [6:0] cfg_channel=0;
    reg signed [23:0] cfg_gain=0;
    reg signed [31:0] cfg_offset=0;
    wire cfg_ready,mic_clk,started,acquisition_active;
    tri [63:0] pdm_data;
    reg [63:0] hi='z,lo='z;
    assign pdm_data=hi;assign pdm_data=lo;
    reg [7:0] gmii_rxd=0;
    reg gmii_rx_dv=0,gmii_rx_er=0;
    wire [7:0] gmii_txd;
    wire gmii_tx_en,gmii_tx_er,overflow,processing_error,clipped,framing_error,tx_error,tx_packet_done;
    wire [31:0] dropped_frames,stream_epoch;
    mems_ethernet_core #(.STARTUP_CYCLES(STARTUP),.ARP_RETRY_CYCLES(125000)) dut(
        .audio_clk(audio_clk),.eth_clk(eth_clk),.rx_clk(rx_clk),.rst_n(rst_n),.run(run),.link_up(link_up),.selftest_mode(1'b0),
        .pdm_data(pdm_data),.mic_clk(mic_clk),.started(started),.acquisition_active(acquisition_active),
        .cfg_valid(cfg_valid),.cfg_channel(cfg_channel),.cfg_gain(cfg_gain),.cfg_offset(cfg_offset),.cfg_ready(cfg_ready),
        .gmii_rxd(gmii_rxd),.gmii_rx_dv(gmii_rx_dv),.gmii_rx_er(gmii_rx_er),
        .gmii_txd(gmii_txd),.gmii_tx_en(gmii_tx_en),.gmii_tx_er(gmii_tx_er),
        .overflow(overflow),.processing_error(processing_error),.clipped(clipped),.framing_error(framing_error),.tx_error(tx_error),
        .dropped_frames(dropped_frames),.stream_epoch(stream_epoch),.tx_packet_done(tx_packet_done),
        .selftest_pass(),.selftest_fail(),.selftest_tx_pass(),.selftest_tx_fail(),.debug_audio(),.debug_eth(),.debug_rx(),
        .parity_cfg_valid(1'b0),.parity_even_gain(24'd4194304),.parity_odd_gain(24'd4194304),.parity_cfg_ready(),
        .parity_active_even_gain(),.parity_active_odd_gain(),.monitor_pcm_valid(),.monitor_pcm_channel(),.monitor_pcm_data());
    // Check conservation of every accepted sample, including its metadata,
    // across the added elastic stage under the real congestion/reset tests.
    reg [99:0] audio_queue[0:3],stalled_word;
    integer audio_qrd=0,audio_qwr=0,audio_qcount=0;
    integer staged_samples=0,audio_stall_cycles=0;
    bit audio_was_stalled=0;
    always @(posedge audio_clk or negedge dut.audio_stream_rst_n) begin
        if(!dut.audio_stream_rst_n) begin
            audio_qrd=0;audio_qwr=0;audio_qcount=0;audio_was_stalled=0;
        end else begin
            if(audio_was_stalled && (!dut.sample_fifo.wr_valid ||
                dut.sample_fifo.wr_data !== stalled_word))
                $fatal(1,"[TB_ERROR] audio sample changed while backpressured");
            if(dut.sample_fifo.wr_valid && dut.sample_fifo.wr_ready) begin
                if(audio_qcount==0 || dut.sample_fifo.wr_data !== audio_queue[audio_qrd])
                    $fatal(1,"[TB_ERROR] audio pipeline lost/reordered data or metadata");
                audio_qrd=(audio_qrd+1)%4;audio_qcount=audio_qcount-1;
                staged_samples=staged_samples+1;
            end
            if(dut.pcm_valid && dut.pcm_ready) begin
                if(audio_qcount==4)$fatal(1,"[TB_ERROR] audio pipeline scoreboard overflow");
                audio_queue[audio_qwr]={processing_error,overflow,clipped,
                    dut.pcm_frame_id,dut.pcm_channel,dut.pcm_first,dut.pcm_last,dut.pcm_data};
                audio_qwr=(audio_qwr+1)%4;audio_qcount=audio_qcount+1;
            end
            audio_was_stalled=dut.sample_fifo.wr_valid && !dut.sample_fifo.wr_ready;
            stalled_word=dut.sample_fifo.wr_data;
            if(audio_was_stalled)audio_stall_cycles=audio_stall_cycles+1;
        end
    end
    reg [127:0] pdm[0:N-1];
    reg [3071:0] expected_pcm[0:255];
    reg [55:0] calibration[0:127];
    integer raw_period=-1;
    function automatic [63:0] pdm_phase(input integer p,input bit odd);
        integer c,idx;
        begin
            idx=p-STARTUP;
            for(c=0;c<64;c=c+1) pdm_phase[c]=(idx>=0 && idx<N)?pdm[idx][2*c+odd]:(p%2);
        end
    endfunction
    always @(negedge acquisition_active) raw_period=-1;
    always @(posedge mic_clk) begin raw_period=raw_period+1;lo<=#30 'z;hi<=#120 pdm_phase(raw_period,1);end
    always @(negedge mic_clk) begin hi<=#30 'z;lo<=#120 pdm_phase(raw_period,0);end

    // Independent MSB-first Ethernet CRC (bit order is reversed at the end).
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
    byte unsigned tx_frame[0:1599],arp[0:63];
    integer tx_count=0,arp_count=0,udp_count=0,epoch_packets=0,pcm_compared=0;
    integer last_id=95,gaps=0,epoch=0,payload_file;
    bit was_en=0;
    reg [31:0] expected_crc;
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
        integer i,j,r,c,p,frame_id;
        integer unsigned sum;
        reg [31:0] crc;
        reg [63:0] sequence_value,id_value;
        reg [23:0] sample_value;
        begin
            if(tx_count<72)$fatal(1,"[TB_ERROR] short Ethernet frame");
            for(i=0;i<7;i=i+1)if(tx_frame[i]!=8'h55)$fatal(1,"[TB_ERROR] preamble");
            if(tx_frame[7]!=8'hd5)$fatal(1,"[TB_ERROR] SFD");
            crc='1;for(i=8;i<tx_count-4;i=i+1)crc=crc_step(crc,tx_frame[i]);crc=crc_finish(crc);
            for(i=0;i<4;i=i+1)if(tx_frame[tx_count-4+i]!=((crc>>(8*i))&255))$fatal(1,"[TB_ERROR] FCS");
            if({tx_frame[20],tx_frame[21]}==16'h0806)arp_count=arp_count+1;
            else begin
                if(tx_count!=1262 || {tx_frame[20],tx_frame[21]}!=16'h0800)$fatal(1,"[TB_ERROR] Ethernet length/type");
                if({tx_frame[24],tx_frame[25]}!=1236 || tx_frame[31]!=17)$fatal(1,"[TB_ERROR] IP length/protocol");
                sum=0;for(i=22;i<42;i=i+2)sum=sum+tx_frame[i]*256+tx_frame[i+1];
                while(sum>65535)sum=(sum&65535)+(sum>>16);
                if(sum!=65535)$fatal(1,"[TB_ERROR] IPv4 checksum");
                if({tx_frame[42],tx_frame[43]}!=5000 || {tx_frame[44],tx_frame[45]}!=5000 ||
                    {tx_frame[46],tx_frame[47]}!=1216)$fatal(1,"[TB_ERROR] UDP ports/length");
                sum=17+1216;
                for(i=34;i<42;i=i+2)sum=sum+tx_frame[i]*256+tx_frame[i+1];
                for(i=42;i<1258;i=i+2)sum=sum+tx_frame[i]*256+tx_frame[i+1];
                while(sum>65535)sum=(sum&65535)+(sum>>16);
                if(sum!=65535 || {tx_frame[48],tx_frame[49]}==0)$fatal(1,"[TB_ERROR] UDP checksum");
                p=50;
                if({tx_frame[p],tx_frame[p+1],tx_frame[p+2],tx_frame[p+3]}!=32'h4d313238 ||
                   tx_frame[p+4]!=1 || tx_frame[p+5]!=32 || tx_frame[p+6]!=1 || tx_frame[p+7]!=128 ||
                   {tx_frame[p+8],tx_frame[p+9],tx_frame[p+10],tx_frame[p+11]}!=48000 ||
                   {tx_frame[p+12],tx_frame[p+13]}!=3 || {tx_frame[p+14],tx_frame[p+15]}!=392)
                    $fatal(1,"[TB_ERROR] M128 format");
                sequence_value=0;for(i=0;i<8;i=i+1)sequence_value=(sequence_value<<8)|tx_frame[p+16+i];
                if(sequence_value!=epoch_packets || {tx_frame[p+24],tx_frame[p+25],tx_frame[p+26],tx_frame[p+27]}!=epoch)
                    $fatal(1,"[TB_ERROR] stream epoch/sequence");
                if((tx_frame[p+31]&12)!=0)$fatal(1,"[TB_ERROR] processing/framing flags");
                for(r=0;r<3;r=r+1)begin
                    j=p+32+r*392;id_value=0;
                    for(i=0;i<8;i=i+1)id_value=(id_value<<8)|tx_frame[j+i];
                    frame_id=id_value;
                    if(id_value>255 || frame_id<=last_id)$fatal(1,"[TB_ERROR] frame order/range id=%0d last=%0d",frame_id,last_id);
                    if(frame_id!=last_id+1)begin
                        if(epoch!=3)$fatal(1,"[TB_ERROR] ARP-gated stream lost a frame");
                        gaps=gaps+(frame_id-last_id-1);
                    end
                    last_id=frame_id;
                    for(c=0;c<128;c=c+1)begin
                        sample_value={tx_frame[j+8+c*3+2],tx_frame[j+8+c*3+1],tx_frame[j+8+c*3]};
                        if(sample_value!==expected_pcm[frame_id][24*c +: 24])
                            $fatal(1,"[TB_ERROR] golden mismatch epoch=%0d id=%0d ch=%0d got=%h expected=%h",
                                epoch,frame_id,c,sample_value,expected_pcm[frame_id][24*c +:24]);
                        pcm_compared=pcm_compared+1;
                    end
                end
                // One payload per hexadecimal line also feeds the Python host decoder test.
                for(i=50;i<1258;i=i+1)$fwrite(payload_file,"%02x",tx_frame[i]);
                $fwrite(payload_file,"\n");
                udp_count=udp_count+1;epoch_packets=epoch_packets+1;
            end
        end
    endtask
    always @(negedge eth_clk)begin
        if(gmii_tx_er)$fatal(1,"[TB_ERROR] GMII TX error");
        if(gmii_tx_en)begin
            if(!was_en)tx_count=0;
            if(tx_count>=1600)$fatal(1,"[TB_ERROR] oversized frame");
            tx_frame[tx_count]=gmii_txd;tx_count=tx_count+1;
        end else if(was_en)check_frame();
        was_en=gmii_tx_en;
        if(processing_error || framing_error)$fatal(1,"[TB_ERROR] unexpected internal error");
    end
    integer c,before_arp;
    initial begin
        $readmemh("../tb/vectors/pdm.hex",pdm);
        $readmemh("../tb/vectors/expected_pcm.hex",expected_pcm);
        $readmemh("../tb/vectors/calibration.hex",calibration);
        payload_file=$fopen("../log/net_core/payloads.hex","w");
        if(!payload_file)$fatal(1,"[TB_ERROR] payload export open failed");
        repeat(8)@(negedge audio_clk);rst_n=1;
        repeat(8)@(negedge audio_clk);
        for(c=0;c<128;c=c+1)begin
            cfg_valid=1;cfg_channel=c;cfg_gain=calibration[c][55:32];cfg_offset=calibration[c][31:0];
            @(negedge audio_clk);
        end
        cfg_valid=0;run=1;
        for(epoch=1;epoch<=3;epoch=epoch+1)begin
            before_arp=arp_count;epoch_packets=0;last_id=95;
            @(negedge eth_clk);link_up=1;
            wait(arp_count>before_arp);
            if(epoch<=2)begin
                // Delays longer than the finite queue capacity must not start
                // capture. Epoch 2 also requires an autonomous ARP retry.
                if(epoch==1) #650000; else #2000000;
                if(acquisition_active || mic_clk || overflow || dropped_frames!=0 || dut.pcm_valid)
                    $fatal(1,"[TB_ERROR] capture/overflow before peer resolution");
                if(epoch==2 && arp_count<before_arp+2)
                    $fatal(1,"[TB_ERROR] ARP retries require a queued PCM packet");
            end
            arp_reply();
            if(epoch<=2)wait(epoch_packets==53);
            else begin
                // Retain the genuine downstream-congestion test, now after
                // resolution rather than relying on the startup bug.
                wait(epoch_packets==4);
                force dut.network.tx_payload_ready=1'b0;
                #650000;
                if(!overflow || dropped_frames==0)$fatal(1,"[TB_ERROR] forced backpressure did not exercise whole-frame drop");
                release dut.network.tx_payload_ready;
                wait(last_id>=250);
            end
            @(posedge eth_clk);
            $display("[TB_DATA] epoch=%0d packets=%0d last_frame=%0d dropped_frames=%0d gaps=%0d PCM_exact=%0d",
                epoch,epoch_packets,last_id,dropped_frames,gaps,pcm_compared);
            if(epoch<=2 && (overflow || dropped_frames!=0))$fatal(1,"[TB_ERROR] delayed-ARP stream overflow");
            if(epoch==3 && (gaps==0 || !overflow))$fatal(1,"[TB_ERROR] missing forced-congestion gap/status");
            link_up=0;
            repeat(40)@(negedge eth_clk);
            if(acquisition_active || mic_clk || gmii_tx_en)$fatal(1,"[TB_ERROR] linkdown flush");
        end
        if(tx_error)$fatal(1,"[TB_ERROR] valid stream TX error");
        run=0;rst_n=0;repeat(8)@(negedge eth_clk);
        $fclose(payload_file);
        if(audio_stall_cycles==0 || staged_samples==0)
            $fatal(1,"[TB_ERROR] audio pipeline coverage missing");
        $display("[TB_INFO] Audio pipeline samples=%0d stalled_cycles=%0d",staged_samples,audio_stall_cycles);
        $display("[TB_INFO] End-to-end PDM to UDP PASS packets=%0d samples=%0d gaps=%0d",udp_count,pcm_compared,gaps);
        $display("[TB_INFO] Simulation Finished!");$finish;
    end
    initial begin #26000000;$fatal(1,"[TB_ERROR] Watchdog");end
endmodule
