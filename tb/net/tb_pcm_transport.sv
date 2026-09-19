`timescale 1ns/1ps
module tb_pcm_transport;
    reg wr_clk=0,rd_clk=0;
    always #4.069 wr_clk=~wr_clk;
    always #4 rd_clk=~rd_clk;
    reg wr_rst_n=0,rd_rst_n=0;
    reg [99:0] wr_data=0;
    reg wr_valid=0;
    wire wr_ready;
    wire [99:0] rd_data;
    wire rd_valid,rd_ready;
    reg [31:0] epoch=32'h12345678;
    wire [7:0] payload_data;
    wire payload_valid,payload_last,framing_error,packet_accepted;
    wire [15:0] payload_length;
    reg payload_ready=0,force_stall=0;
    // Deliberately tiny FIFO: frequent full conditions and Gray pointer wraps.
    async_sample_fifo #(.WIDTH(100),.ADDRESS_BITS(4)) fifo (
        .wr_clk(wr_clk),.wr_rst_n(wr_rst_n),.wr_data(wr_data),
        .wr_valid(wr_valid),.wr_ready(wr_ready),.rd_clk(rd_clk),
        .rd_rst_n(rd_rst_n),.rd_data(rd_data),.rd_valid(rd_valid),.rd_ready(rd_ready));
    pcm_udp_packetizer packetizer (
        .clk(rd_clk),.rst_n(rd_rst_n),.stream_epoch(epoch),.selftest_mode(1'b0),.selftest_error(1'b0),
        .sample_data(rd_data[23:0]),.sample_channel(rd_data[30:24]),
        .sample_frame_id(rd_data[94:31]),.sample_first(rd_data[95]),
        .sample_last(rd_data[96]),.sample_status(rd_data[99:97]),
        .sample_valid(rd_valid),.sample_ready(rd_ready),
        .payload_data(payload_data),.payload_valid(payload_valid),
        .payload_ready(payload_ready),.payload_last(payload_last),
        .payload_length(payload_length),.framing_error(framing_error),
        .packet_accepted(packet_accepted));

    integer checks=0,push_count=0,pop_count=0,full_cycles=0,output_stall_cycles=0;
    integer fifo_head=0,fifo_tail=0;
    reg [99:0] fifo_expected[0:16383];
    reg input_stalled=0,fifo_stalled=0,payload_stalled=0;
    reg [99:0] held_input,held_fifo;
    reg [7:0] held_byte;
    reg held_last;
    reg [7:0] expected_bytes[0:15][0:1207];
    integer expected_count=0,complete_packets=0,byte_number=0,accepted_pulses=0;
    reg [31:0] producer_rng=32'hda3714bf,consumer_rng=32'h164cac9e;
    integer consumer_pause=0;
    reg last_stalled=0;

    task automatic check(input bit okay,input string message_text);
        begin
            checks=checks+1;
            if(!okay) begin
                $display("[TB_ERROR] %s at %0t",message_text,$time);
                $fatal(1,"PCM transport verification failed");
            end
        end
    endtask

    function automatic [31:0] next_random(input [31:0] value);
        reg [31:0] temp;
        begin
            temp=value^(value<<13);temp=temp^(temp>>17);
            next_random=temp^(temp<<5);
        end
    endfunction

    function automatic [23:0] sample_value(input [63:0] frame_id,input integer channel);
        begin
            case(channel%8)
                0:sample_value=24'h800000;
                1:sample_value=24'h7fffff;
                2:sample_value=24'hffffff;
                3:sample_value=24'h000000;
                4:sample_value=(frame_id^(frame_id>>24)) + channel*24'h010201;
                5:sample_value=24'h800001;
                6:sample_value=24'h123456;
                7:sample_value=24'h654321;
            endcase
        end
    endfunction

    // Expected bytes are built from protocol fields and intended full frames,
    // independently of the FIFO/packetizer internal addresses and state machine.
    task automatic expect_packet(input [63:0] sequence_id,input [31:0] stream_id,
        input [31:0] flags,input [63:0] frame0,frame1,frame2);
        integer p,b,r,c,start;
        reg [63:0] fid;
        reg [23:0] value;
        begin
            p=expected_count;
            check(p<16,"Expected packet storage exhausted");
            for(b=0;b<1208;b=b+1) expected_bytes[p][b]=0;
            expected_bytes[p][0]="M";expected_bytes[p][1]="1";
            expected_bytes[p][2]="2";expected_bytes[p][3]="8";
            expected_bytes[p][4]=1;expected_bytes[p][5]=32;
            expected_bytes[p][6]=1;expected_bytes[p][7]=128;
            expected_bytes[p][10]=8'hbb;expected_bytes[p][11]=8'h80;
            expected_bytes[p][13]=3;expected_bytes[p][14]=1;expected_bytes[p][15]=8'h88;
            for(b=0;b<8;b=b+1) expected_bytes[p][16+b]=(sequence_id>>(56-8*b));
            for(b=0;b<4;b=b+1) begin
                expected_bytes[p][24+b]=(stream_id>>(24-8*b));
                expected_bytes[p][28+b]=(flags>>(24-8*b));
            end
            for(r=0;r<3;r=r+1) begin
                case(r)
                    0:fid=frame0;
                    1:fid=frame1;
                    2:fid=frame2;
                endcase
                start=32+r*392;
                for(b=0;b<8;b=b+1) expected_bytes[p][start+b]=(fid>>(56-8*b));
                for(c=0;c<128;c=c+1) begin
                    value=sample_value(fid,c);
                    for(b=0;b<3;b=b+1) expected_bytes[p][start+8+c*3+b]=(value>>(8*b));
                end
            end
            expected_count=expected_count+1;
        end
    endtask

    task automatic send_sample(input [63:0] fid,input [6:0] channel,
        input bit first_bit,last_bit,input [2:0] status);
        integer gaps;
        begin
            producer_rng=next_random(producer_rng);
            gaps=producer_rng[1:0];
            repeat(gaps) @(negedge wr_clk);
            @(negedge wr_clk);
            wr_data={status,last_bit,first_bit,fid,channel,sample_value(fid,channel)};
            wr_valid=1;
            @(posedge wr_clk);
            while(!wr_ready) @(posedge wr_clk);
            @(negedge wr_clk);wr_valid=0;
        end
    endtask

    task automatic send_frame(input [63:0] fid,input [2:0] flags);
        integer c;
        begin
            for(c=0;c<128;c=c+1)
                // Flag the LAST sample to detect stale aggregate snapshots.
                send_sample(fid,c,c==0,c==127,c==127 ? flags : 3'd0);
        end
    endtask

    task automatic wait_packets(input integer target);
        integer cycles;
        begin
            cycles=0;
            while(complete_packets<target && cycles<200000) begin
                @(negedge rd_clk);cycles=cycles+1;
            end
            check(complete_packets==target,"Timeout or extra completed payload");
            repeat(8) @(negedge rd_clk);
            check(accepted_pulses==complete_packets,"packet_accepted count/last-byte handshake mismatch");
        end
    endtask

    task automatic reset_stream(input [31:0] new_epoch);
        begin
            @(negedge wr_clk);wr_rst_n=0;rd_rst_n=0;wr_valid=0;
            repeat(10) @(negedge wr_clk);
            check(!wr_ready && !rd_valid && !payload_valid && !framing_error,
                  "Reset failed to clear interface state");
            // Discard any expectation for an intentionally aborted packet.
            expected_count=complete_packets;
            epoch=new_epoch;
            @(negedge wr_clk);wr_rst_n=1;
            repeat(3) @(negedge rd_clk);
            rd_rst_n=1;
        end
    endtask

    always @(negedge rd_clk) begin
        if(!rd_rst_n) begin
            payload_ready=0;consumer_pause=0;last_stalled=0;
        end else begin
            consumer_rng=next_random(consumer_rng);
            if(force_stall) payload_ready=0;
            else if(consumer_pause>0) begin payload_ready=0;consumer_pause=consumer_pause-1;end
            else if(payload_valid && payload_last && !last_stalled) begin
                payload_ready=0;consumer_pause=4;last_stalled=1;
            end else if(consumer_rng[4:0]==0) begin payload_ready=0;consumer_pause=20;end
            else payload_ready=consumer_rng[1:0]!=0;
            if(packet_accepted) last_stalled=0;
        end
    end

    always @(posedge wr_clk) begin
        if(!wr_rst_n) begin fifo_head=0;input_stalled=0;end
        else begin
            if(input_stalled) check(wr_valid && wr_data===held_input,"Producer changed blocked sample");
            input_stalled=wr_valid && !wr_ready;
            held_input=wr_data;
            if(input_stalled) full_cycles=full_cycles+1;
            if(wr_valid && wr_ready) begin
                check(fifo_head<16384,"FIFO scoreboard exhausted");
                fifo_expected[fifo_head]=wr_data;fifo_head=fifo_head+1;
                push_count=push_count+1;
            end
        end
    end

    always @(posedge rd_clk) begin
        if(!rd_rst_n) begin
            fifo_tail=0;fifo_stalled=0;payload_stalled=0;byte_number=0;
        end else begin
            if(fifo_stalled) check(rd_valid && rd_data===held_fifo,"FIFO staged output changed under backpressure");
            fifo_stalled=rd_valid && !rd_ready;held_fifo=rd_data;
            if(rd_valid && rd_ready) begin
                check(fifo_tail<fifo_head,"FIFO emitted an unwritten/reset-old sample");
                check(rd_data===fifo_expected[fifo_tail],"FIFO changed order or sample metadata at clock crossing");
                fifo_tail=fifo_tail+1;pop_count=pop_count+1;
            end
            if(payload_stalled)
                check(payload_valid && payload_data===held_byte && payload_last===held_last,
                      "Payload changed or disappeared during output stall");
            payload_stalled=payload_valid && !payload_ready;
            held_byte=payload_data;held_last=payload_last;
            if(payload_stalled) output_stall_cycles=output_stall_cycles+1;
            if(payload_valid && payload_ready) begin
                check(complete_packets<expected_count,"Unexpected payload from partial/corrupt frames");
                check(payload_length==1208,"Incorrect UDP payload length");
                check(payload_data===expected_bytes[complete_packets][byte_number],
                    $sformatf("packet%0d byte%0d got%02x expected%02x",complete_packets,byte_number,
                    payload_data,expected_bytes[complete_packets][byte_number]));
                check(payload_last===(byte_number==1207),"payload_last is early or late");
                if(byte_number==1207) begin
                    complete_packets=complete_packets+1;byte_number=0;
                end else byte_number=byte_number+1;
            end
            if(packet_accepted) begin
                accepted_pulses=accepted_pulses+1;
                check(accepted_pulses==complete_packets,"Packet accepted before final byte or twice");
            end
        end
    end

    integer i;
    initial begin
        reset_stream(32'h12345678);
        expect_packet(0,epoch,7,64'd10,64'd11,64'd20);
        expect_packet(1,epoch,3,64'd1000,64'd1004,64'd1005);
        expect_packet(2,epoch,4,64'h1234567812345678,64'hfedcba9876543210,64'hfffffffffffffffe);
        expect_packet(3,epoch,0,64'hffffffffffffffff,64'd0,64'd999999);
        send_frame(10,1);send_frame(11,2);send_frame(20,4);
        send_frame(1000,1);send_frame(1004,2);send_frame(1005,0);
        send_frame(64'h1234567812345678,0);send_frame(64'hfedcba9876543210,0);send_frame(64'hfffffffffffffffe,4);
        send_frame(64'hffffffffffffffff,0);send_frame(0,0);send_frame(999999,0);
        wait_packets(4);
        check(!framing_error,"Valid frames caused a framing error");
        $display("[TB_DATA] 4 packets/4832 bytes, independent64-bit frame IDs, signed24 LE extrema, randomized CDC/backpressure PASS");

        // A reset discards complete and partial frames that have not formed a packet.
        send_frame(100,1);
        for(i=0;i<55;i=i+1) send_sample(101,i,i==0,0,0);
        reset_stream(32'h87654321);
        expect_packet(0,epoch,8,64'd303,64'd304,64'd400);
        send_frame(200,1);send_frame(201,2);
        for(i=0;i<16;i=i+1) send_sample(202,i,i==0,0,0);
        for(i=17;i<128;i=i+1) send_sample(202,i,0,i==127,4); // Missing channel16.
        send_frame(300,1);
        for(i=0;i<31;i=i+1) send_sample(301,i,i==0,0,0);
        send_sample(302,31,0,0,4); // Frame ID changes in the middle of one record.
        for(i=32;i<128;i=i+1) send_sample(301,i,0,i==127,0);
        send_frame(303,0);send_frame(304,0);send_frame(400,0);
        wait_packets(5);
        check(framing_error,"Corrupt frame did not set framing_error");
        $display("[TB_DATA] Reset partial-frame discard; skipped channel and mid-frame ID corruption discarded without stale flags/data PASS");

        expect_packet(1,epoch,9,64'd500,64'd501,64'd510);
        for(i=0;i<9;i=i+1) send_sample(450,i,i==0,i==8,0); // Premature last.
        for(i=0;i<10;i=i+1) send_sample(451,i,i==0,0,2);
        // This first sample is itself the resynchronization point.
        send_frame(500,1);send_frame(501,0);send_frame(510,0);
        wait_packets(6);
        $display("[TB_DATA] Early-last and new-first resynchronization, sticky framing flag and sequence continuity PASS");

        force_stall=1;
        expect_packet(2,epoch,8,64'd600,64'd601,64'd602);
        send_frame(600,0);send_frame(601,0);send_frame(602,0);
        wait(payload_valid);
        // Additional samples are now queued across the CDC while SEND is blocked.
        for(i=0;i<12;i=i+1) send_sample(603,i,i==0,0,0);
        repeat(100) @(negedge rd_clk);
        check(complete_packets==6 && payload_valid,"Intentional output stall failed");
        reset_stream(32'h01020304);
        force_stall=0;
        expect_packet(0,epoch,0,64'd700,64'd800,64'd900);
        send_frame(700,0);send_frame(800,0);send_frame(900,0);
        wait_packets(7);
        check(!framing_error,"Reset did not clear sticky framing_error");
        repeat(1000) @(negedge rd_clk);
        check(complete_packets==7 && !payload_valid && fifo_head==fifo_tail,"Unexpected residual data after reset recovery");
        check(full_cycles>100 && output_stall_cycles>1000,"Insufficient FIFO-full/output-stall coverage");
        $display("[TB_DATA] Reset during held payload with queued CDC samples; new epoch/sequence0 and no stale output PASS");
        $display("[TB_DATA] packets=%0d bytes=%0d pushes=%0d pops=%0d full_cycles=%0d output_stalls=%0d checks=%0d",
            complete_packets,complete_packets*1208,push_count,pop_count,full_cycles,output_stall_cycles,checks);
        $display("[TB_INFO] Simulation Finished!");
        $finish;
    end
    initial begin
        #20000000;
        $fatal(1,"[TB_ERROR] Transport global timeout");
    end
endmodule
