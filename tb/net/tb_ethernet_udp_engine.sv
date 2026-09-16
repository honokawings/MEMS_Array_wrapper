`timescale 1ns/1ps
module tb_ethernet_udp_engine;
    localparam [47:0] LM=48'h020000000128, PM=48'h102030405060;
    localparam [31:0] LI=32'hc0a80a02, PI=32'hc0a80a01;
    reg clk=0, rx_clk=0, rx_clock_running=1;
    always #4 clk=~clk;
    always #4.3 if(rx_clock_running) rx_clk=~rx_clk;
    reg rst_n=0, link_up=0;
    reg [7:0] tx_payload_data=0;
    reg tx_payload_valid=0, tx_payload_last=0;
    reg [15:0] tx_payload_length=0;
    wire tx_payload_ready, tx_packet_done, tx_error;
    reg [7:0] gmii_rxd=0;
    reg gmii_rx_dv=0, gmii_rx_er=0;
    wire [7:0] gmii_txd;
    wire gmii_tx_en, gmii_tx_er;
    ethernet_udp_engine #(.ARP_RETRY_CYCLES(5000)) dut(.*);

    byte unsigned payload[0:1471];
    byte unsigned frame[0:1600];
    byte unsigned rx_frame[0:1600];
    byte unsigned expected[0:63][0:1600];
    integer expected_length[0:63];
    integer queued=0, checked=0, monitor_index=0, idle_cycles=1000;
    integer done_count=0, total_bytes=0;
    reg was_en=0, suppress_abort=0;
    integer ident=0,expected_udp_count=0;
    // Independent MSB-first CRC implementation: reverse each incoming octet,
    // use polynomial 04c11db7, then bit-reverse the completed register.
    function automatic [31:0] crc_step(input [31:0] old, input [7:0] b);
        reg [31:0] c; reg feedback; integer i;
        begin
            c=old;
            for (i=0;i<8;i=i+1) begin
                feedback=c[31]^b[i]; c=c<<1;
                if(feedback) c=c^32'h04c11db7;
            end
            crc_step=c;
        end
    endfunction
    function automatic [31:0] reversed_complement(input [31:0] c);
        integer j;
        begin for(j=0;j<32;j=j+1) reversed_complement[j]=~c[31-j]; end
    endfunction
    function automatic [15:0] checksum(input integer unsigned s);
        integer unsigned v;
        begin
            v=s;
            while(v>65535) v=(v&65535)+(v>>16);
            checksum=(~v)&65535;
        end
    endfunction
    task automatic fail(input string message);
        begin $display("[TB_ERROR] %0t %s",$time,message); $fatal(1); end
    endtask
    task automatic put_mac(input integer p,input [47:0] v);
        integer i; begin for(i=0;i<6;i=i+1) frame[p+i]=(v>>((5-i)*8))&255; end
    endtask
    task automatic put_ip(input integer p,input [31:0] v);
        integer i; begin for(i=0;i<4;i=i+1) frame[p+i]=(v>>((3-i)*8))&255; end
    endtask
    task automatic put_word(input integer p,input [15:0] v);
        begin frame[p]=v[15:8];frame[p+1]=v[7:0];end
    endtask
    task automatic finish_frame(input integer length_without_fcs);
        reg [31:0] c,v; integer i;
        begin
            c=32'hffffffff;
            for(i=0;i<length_without_fcs;i=i+1) c=crc_step(c,frame[i]);
            v=reversed_complement(c);
            for(i=0;i<4;i=i+1) frame[length_without_fcs+i]=(v>>(i*8))&255;
        end
    endtask
    task automatic queue_frame(input integer n);
        integer i;
        begin
            if(queued>=64) fail("expected frame queue exhausted");
            for(i=0;i<7;i=i+1) expected[queued][i]=8'h55;
            expected[queued][7]=8'hd5;
            for(i=0;i<n;i=i+1) expected[queued][i+8]=frame[i];
            expected_length[queued]=n+8; queued=queued+1;
        end
    endtask
    task automatic make_arp(input bit outgoing, input bit request,
        input [47:0] remote_mac,input [31:0] remote_ip);
        integer i;
        begin
            for(i=0;i<1601;i=i+1) frame[i]=0;
            if(outgoing) begin
                put_mac(0,request?48'hffffffffffff:remote_mac); put_mac(6,LM);
                put_mac(22,LM);put_ip(28,LI);
                put_mac(32,request?48'b0:remote_mac);put_ip(38,remote_ip);
            end else begin
                put_mac(0,request?48'hffffffffffff:LM);put_mac(6,remote_mac);
                put_mac(22,remote_mac);put_ip(28,remote_ip);
                put_mac(32,request?48'b0:LM);put_ip(38,LI);
            end
            put_word(12,16'h0806);put_word(14,1);put_word(16,16'h0800);
            frame[18]=6;frame[19]=4;put_word(20,request?1:2);
            finish_frame(60);
        end
    endtask
    task automatic pattern(input integer n,input integer seed);
        integer i;
        begin for(i=0;i<n;i=i+1) payload[i]=(i*73+(i>>2)*19+seed)&255; end
    endtask
    task automatic queue_udp(input integer n);
        integer i,bl; integer unsigned sum; reg [15:0] ck;
        begin
            for(i=0;i<1601;i=i+1) frame[i]=0;
            put_mac(0,PM);put_mac(6,LM);put_word(12,16'h0800);
            frame[14]=8'h45;put_word(16,n+28);put_word(18,ident);
            put_word(20,16'h4000);frame[22]=64;frame[23]=17;
            put_ip(26,LI);put_ip(30,PI);
            sum=0;for(i=14;i<34;i=i+2) sum=sum+(frame[i]*256)+frame[i+1];
            put_word(24,checksum(sum));
            put_word(34,5000);put_word(36,5000);put_word(38,n+8);
            for(i=0;i<n;i=i+1) frame[42+i]=payload[i];
            sum=LI[31:16]+LI[15:0]+PI[31:16]+PI[15:0]+17+(n+8);
            for(i=34;i<42+n;i=i+2) sum=sum+(frame[i]*256)+frame[i+1];
            ck=checksum(sum);put_word(40,ck==0?16'hffff:ck);
            bl=(n+42<60)?60:n+42;
            finish_frame(bl);queue_frame(bl+4);ident=ident+1;expected_udp_count=expected_udp_count+1;
        end
    endtask
    task automatic drive_payload(input integer n,input bit gaps);
        integer i;
        begin
            for(i=0;i<n;i=i+1) begin
                @(negedge clk);
                tx_payload_data=payload[i];tx_payload_length=n;
                tx_payload_valid=1;tx_payload_last=(i==n-1);
                @(posedge clk);
                while(!tx_payload_ready) @(posedge clk);
                if(gaps && i%7==3) begin
                    @(negedge clk);tx_payload_valid=0;
                    repeat(3) @(negedge clk);
                end
            end
            @(negedge clk);tx_payload_valid=0;tx_payload_last=0;
        end
    endtask
    task automatic send_rx(input integer n,input integer error_byte,input bit bad_preamble);
        integer i;
        begin
            for(i=0;i<n;i=i+1) rx_frame[i]=frame[i];
            for(i=0;i<8;i=i+1) begin
                @(negedge rx_clk);gmii_rx_dv=1;gmii_rx_er=0;
                gmii_rxd=i==7?8'hd5:(bad_preamble&&i==3?8'h54:8'h55);
            end
            for(i=0;i<n;i=i+1) begin
                @(negedge rx_clk);gmii_rxd=rx_frame[i];gmii_rx_er=(i==error_byte);
            end
            @(negedge rx_clk);gmii_rx_dv=0;gmii_rx_er=0;
            repeat(16) @(negedge rx_clk);
        end
    endtask
    task automatic await_frames;
        integer cycles;
        begin
            cycles=0;
            while(checked!=queued && cycles<10000) begin @(negedge clk); cycles=cycles+1;end
            if(checked!=queued) fail($sformatf("timeout waiting frames %0d/%0d",checked,queued));
            repeat(20) @(negedge clk);
        end
    endtask

    always @(negedge clk) begin
        if(rst_n) begin
            if(gmii_tx_er) fail("GMII error asserted");
            if(tx_packet_done) done_count=done_count+1;
            if(suppress_abort) begin was_en=0;monitor_index=0;idle_cycles=1000;end
            else if(gmii_tx_en) begin
                if(!was_en) begin
                    if(idle_cycles<12) fail($sformatf("short IFG %0d",idle_cycles));
                    monitor_index=0;
                end
                if(checked>=queued) fail("unexpected transmitted frame");
                if(monitor_index>=expected_length[checked]) fail("overlength transmitted frame");
                if(gmii_txd!==expected[checked][monitor_index])
                    fail($sformatf("frame %0d byte %0d got %02x expected %02x",checked,monitor_index,gmii_txd,expected[checked][monitor_index]));
                monitor_index=monitor_index+1;total_bytes=total_bytes+1;
                was_en=1;idle_cycles=0;
            end else begin
                if(was_en) begin
                    if(monitor_index!=expected_length[checked]) fail("truncated transmitted frame");
                    $display("[TB_MONITOR] verified frame=%0d bytes=%0d",checked,monitor_index);
                    checked=checked+1;
                end
                was_en=0;idle_cycles=idle_cycles+1;
            end
        end
    end

    integer i,n,before_count;
    integer unsigned s;
    reg [15:0] complement;
    reg [31:0] reference_crc;
    time packet_start, max_packet_latency=0;
    initial begin
        reference_crc=32'hffffffff;
        for(i=0;i<9;i=i+1) reference_crc=crc_step(reference_crc,8'h31+i);
        if(reversed_complement(reference_crc)!=32'hcbf43926) fail("independent CRC-32 check vector failed");
        repeat(5) @(negedge clk);
        @(negedge rx_clk);rx_clock_running=0;
        #1.1;rst_n=1;link_up=1;
        repeat(10) @(negedge clk);
        if(dut.rx_rst_n || dut.u_arp_rx.state!=0 || dut.u_arp_rx.message_req)
            fail("RX reset released with RX clock stopped");
        rx_clock_running=1;
        repeat(2) begin
            @(posedge rx_clk);#0.1;
            if(dut.rx_rst_n) fail("RX reset released before three local clock edges");
        end
        @(posedge rx_clk);#0.1;
        if(!dut.rx_rst_n) fail("RX reset failed to release on third local clock edge");
        $display("[TB_DATA] asynchronous global release with stopped RXC: held reset, exactly3 RX edges release PASS");
        repeat(10) @(negedge clk);
        // Unknown peer: hold completed packet until ARP succeeds, retry once.
        pattern(17,1);make_arp(1,1,PM,PI);queue_frame(64);
        drive_payload(17,1);await_frames();
        make_arp(1,1,PM,PI);queue_frame(64);await_frames();
        // All variants have a valid FCS except the intentional corrupt-FCS case.
        for(i=0;i<12;i=i+1) begin
            make_arp(0,0,PM,PI);
            case(i)
                0: frame[60]=frame[60]^1;
                1: begin frame[13]=0;finish_frame(60);end
                2: begin frame[15]=2;finish_frame(60);end
                3: begin frame[17]=1;finish_frame(60);end
                4: begin frame[18]=5;finish_frame(60);end
                5: begin frame[19]=6;finish_frame(60);end
                6: begin frame[21]=3;finish_frame(60);end
                7: begin frame[41]=3;finish_frame(60);end
                8: begin frame[37]=0;finish_frame(60);end
                9: begin frame[11]=1;finish_frame(60);end
                10: begin frame[0]=1;finish_frame(60);end
                11: begin frame[22]=8'h11;frame[6]=8'h11;finish_frame(60);end
            endcase
            send_rx(64,-1,0);
            repeat(40) @(negedge clk);
            if(checked!=2 || dut.peer_valid) fail($sformatf("bad ARP variant %0d accepted",i));
        end
        make_arp(0,0,PM,PI);send_rx(64,30,0);
        make_arp(0,0,PM,PI);send_rx(64,-1,1);
        make_arp(0,0,PM,PI);finish_frame(42);send_rx(46,-1,0);
        make_arp(0,0,PM,PI);finish_frame(1515);send_rx(1519,-1,0);
        if(dut.peer_valid) fail("ER/preamble/runt/oversize ARP accepted");
        queue_udp(17);make_arp(0,0,PM,PI);send_rx(64,-1,0);await_frames();
        // Long, short, odd and MTU limit. Headers, payload, zero padding,
        // checksums and FCS are compared at every GMII byte.
        for(i=0;i<7;i=i+1) begin
            case(i) 0:n=1;1:n=2;2:n=18;3:n=19;4:n=1208;5:n=1471;default:n=1472;endcase
            pattern(n,23+i);queue_udp(n);drive_payload(n,i[0]);await_frames();
        end
        // RFC 768 computed zero must be transmitted as ffff.
        n=2;payload[0]=0;payload[1]=0;
        s=LI[31:16]+LI[15:0]+PI[31:16]+PI[15:0]+17+2*(n+8)+10000;
        complement=checksum(s);payload[0]=complement[15:8];payload[1]=complement[7:0];
        queue_udp(n);
        if(expected[queued-1][48]!=8'hff || expected[queued-1][49]!=8'hff) fail("zero checksum test not constructed");
        drive_payload(n,0);await_frames();
        // Answer ARP requests for local IP, including other on-link clients.
        make_arp(1,0,48'h102030405062,32'hc0a80a03);queue_frame(64);
        make_arp(0,1,48'h102030405062,32'hc0a80a03);send_rx(64,-1,0);await_frames();
        make_arp(1,0,48'h102030405062,32'b0);queue_frame(64);
        make_arp(0,1,48'h102030405062,32'b0);send_rx(64,-1,0);await_frames();
        if(dut.peer_mac!==PM) fail("unrelated ARP replaced fixed-peer entry");
        if(tx_error) fail("tx_error set on valid traffic");
        if(done_count!=9) fail($sformatf("done count %0d expected 9",done_count));
        // Malformed input: early last, length change, late last, zero/oversize length.
        before_count=checked;
        @(negedge clk);tx_payload_valid=1;tx_payload_length=3;tx_payload_last=1;tx_payload_data=0;
        @(negedge clk);tx_payload_length=2;tx_payload_last=0;
        @(negedge clk);tx_payload_length=3;tx_payload_last=1;
        @(negedge clk);tx_payload_length=1;tx_payload_last=0;
        @(negedge clk);tx_payload_last=1;
        @(negedge clk);tx_payload_length=0;
        @(negedge clk);tx_payload_length=1473;
        @(negedge clk);tx_payload_valid=0;tx_payload_last=0;
        repeat(40) @(negedge clk);
        if(!tx_error || checked!=before_count) fail("malformed TX input was not rejected");
        pattern(31,98);queue_udp(31);drive_payload(31,0);await_frames();
        // During-frame link loss aborts the packet and clears the learned MAC.
        suppress_abort=1;pattern(1208,99);drive_payload(1208,0);
        wait(gmii_tx_en);repeat(70) @(negedge clk);link_up=0;
        repeat(30) @(negedge clk);
        if(gmii_tx_en || dut.peer_valid || !tx_error) fail("linkdown did not flush engine");
        suppress_abort=0;link_up=1;repeat(10) @(negedge clk);
        pattern(47,101);make_arp(1,1,PM,PI);queue_frame(64);
        drive_payload(47,0);await_frames();
        queue_udp(47);make_arp(0,0,PM,PI);send_rx(64,-1,0);await_frames();
        // Partial ingress link loss must also discard buffered bytes.
        @(negedge clk);tx_payload_valid=1;tx_payload_length=20;tx_payload_data=8'ha5;
        @(negedge clk);tx_payload_valid=0;link_up=0;
        repeat(30) @(negedge clk);link_up=1;repeat(10) @(negedge clk);
        pattern(21,73);make_arp(1,1,PM,PI);queue_frame(64);
        drive_payload(21,0);await_frames();
        // A peer's ARP request both learns its MAC and receives an ARP reply.
        queue_udp(21);make_arp(1,0,PM,PI);queue_frame(64);
        make_arp(0,1,PM,PI);send_rx(64,-1,0);await_frames();
        // Production packets need <62.5 us service time at 16,000 packets/s.
        // Drive successive packets faster than that and check each latency.
        for(i=0;i<8;i=i+1) begin
            pattern(1208,i+7);queue_udp(1208);packet_start=$time;
            drive_payload(1208,0);await_frames();
            if($time-packet_start>62500) fail("service time exceeds 16k packet/s budget");
            if($time-packet_start>max_packet_latency) max_packet_latency=$time-packet_start;
        end
        // Deterministic broad length sweep with intermittent producer gaps.
        for(i=0;i<20;i=i+1) begin
            n=1+((i*331+87)%1472);pattern(n,i+91);queue_udp(n);
            drive_payload(n,1);await_frames();
        end
        repeat(100) @(negedge clk);
        if(checked!=queued || done_count!=expected_udp_count) fail($sformatf("final completion count frames=%0d/%0d UDP=%0d",checked,queued,done_count));
        @(negedge rx_clk);rx_clock_running=0;
        @(negedge clk);rst_n=0;
        #0.1;
        if(dut.rx_rst_n || dut.u_arp_rx.state!=0 || dut.u_arp_rx.message_req)
            fail("RX reset assertion waited for stopped RX clock");
        repeat(5) @(negedge clk);
        if(tx_error || gmii_tx_en || tx_payload_ready) fail("reset did not clear sticky status/state");
        $display("[TB_INFO] PASS Ethernet engine frames=%0d bytes_compared=%0d UDP=%0d rejected_ARP=16 max_1208B_service_ns=%0d",checked,total_bytes,done_count,max_packet_latency);
        $display("[TB_INFO] Simulation Finished!");$finish;
    end
    initial begin #2000000; fail("watchdog timeout");end
endmodule
