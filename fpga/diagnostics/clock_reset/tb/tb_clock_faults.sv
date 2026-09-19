`timescale 1ns/1fs
module tb_clock_faults;
    reg ref27=0,grs_n=0;
    reg [3:0] source_clk=0,run_clock=15;
    real half0=4.0,half1=500.0/96.0,half2=500.0/122.88,half3=4.0;
    always #(500.0/27.0) ref27=~ref27;
    always #(half0) source_clk[0]=run_clock[0]?~source_clk[0]:0;
    always #(half1) source_clk[1]=run_clock[1]?~source_clk[1]:0;
    always #(half2) source_clk[2]=run_clock[2]?~source_clk[2]:0;
    always #(half3) source_clk[3]=run_clock[3]?~source_clk[3]:0;
    GTP_GRS GRS_INST(.GRS_N(grs_n));
    reg [4:0] key_n=31;
    reg [2:0] pll_lock=7;
    reg common_n=1,audio_n=1,eth_n=1;
    wire [63:0] gray,deltas;
    wire [4:0] led;
    wire [3:0] good,fault;
    genvar g;
    generate for(g=0;g<4;g=g+1) begin:counter
        clock_diag_counter #(.PRESCALE_BITS(4)) u_counter(.clk(source_clk[g]),.gray(gray[g*16+:16]));
    end endgenerate
    clock_observer #(.WINDOW_CYCLES(2700),.PRESCALE_BITS(4),.HEARTBEAT_CYCLES(16)) dut(
        .ref_clk(ref27),.key_n(key_n),.pll_lock(pll_lock),.common_arst_n(common_n),.audio_rst_n(audio_n),
        .eth_rst_n(eth_n),.controller_led(5'b10101),.clocks_gray(gray),.led(led),
        .frequency_good(good),.sticky_fault(fault),.measured_deltas(deltas));
    // Synthetic Gray endpoint samples exercise 16-bit modulo wrap directly.
    reg wrap_tick=0;
    reg [15:0] wrap_bin=0;
    wire [15:0] wrap_gray=(wrap_bin>>1)^wrap_bin;
    wire [15:0] wrap_delta;
    wire wrap_good;
    clock_diag_frequency #(.TARGET_HZ(125000000),.WINDOW_CYCLES(2700),.PRESCALE_BITS(4)) wrap(
        .clk(ref27),.window_tick(wrap_tick),.restart(1'b0),.gray_async(wrap_gray),.good(wrap_good),.last_delta(wrap_delta));
    integer checks=0,k,heartbeat_edges=0,old_edges;
    always @(dut.heartbeat) if(grs_n) heartbeat_edges=heartbeat_edges+1;
    task check(input bit ok,input string message);
        begin checks=checks+1;if(!ok)$fatal(1,"[TB_ERROR] %s at %t good=%b fault=%b",message,$time,good,fault);end
    endtask
    task settle;begin repeat(12)@(negedge ref27);end endtask
    task page(input [4:0] keys);begin @(negedge ref27);key_n=keys;settle();end endtask
    task clear_history;begin page(5'b00111);check(fault===0,"clear history chord");page(31);end endtask
    task wrap_sample(input [15:0] value);
        begin wrap_bin=value;settle();wrap_tick=1;@(negedge ref27);wrap_tick=0;settle();end
    endtask
    initial begin
        #200;grs_n=1;
        #410000;
        check(good===15 && fault===0,"healthy independent sources");
        page(5'b11101);check(led[4:1]===15,"frequency page ordering");
        for(k=0;k<4;k=k+1) begin
            $display("[TB_MONITOR] stop source=%0d with LOCK held high",k);
            run_clock[k]=0;#210000;
            check(good===(4'b1111^(4'b1<<k)),"stopped clock detected independently of LOCK");
            check(led[k+1]===0,"frequency LED names failed source");
            if(k>0)check(fault[k]===1,"stopped generated clock latched");
            run_clock[k]=1;#410000;
            check(good===15,"clock recovery needs valid windows");
            if(k>0)check(fault[k]===1,"fault retained after recovery");
            clear_history();page(5'b11101);
        end
        half2=5.0;#210000;
        check(good[2]===0 && fault[2]===1,"wrong 100 MHz audio clock rejected");
        half2=500.0/122.88;#410000;clear_history();
        page(31);pll_lock[0]=0;settle();
        check(led[1]===0 && fault[1]===1,"96 PLL lock loss");
        check(good===15,"LOCK loss separate from clock monitor");
        pll_lock[0]=1;settle();check(fault[1]===1,"short lock fault is sticky");clear_history();
        audio_n=0;settle();check(fault[0]===1,"local reset drop is sticky");audio_n=1;settle();clear_history();
        page(5'b11011);check(led[4:1]===4'b1110,"reset page nominal mapping");
        // KEY0 intentional reset: observer heartbeat and page selection survive.
        key_n[0]=0;pll_lock=0;common_n=0;audio_n=0;eth_n=0;run_clock=1;
        old_edges=heartbeat_edges;#210000;
        check(fault===0,"intentional simultaneous clock/reset drop masked");
        check(heartbeat_edges>old_edges+100,"reference survives reset and source loss");
        check(led[4:1]===4'b0001,"reset page while KEY0 held");
        key_n[0]=1;run_clock=15;pll_lock=7;common_n=1;audio_n=1;eth_n=1;#410000;
        check(fault===0 && good===15,"intentional reset recovery without false fault");
        page(5'b10111);check(led===5'b10101,"controller page all five bits");
        page(5'b00111);check(led[4:1]===0,"clear chord overrides controller");page(31);
        wrap_sample(16'd65000);wrap_sample(16'd245);wrap_sample(16'd1026);
        check(wrap_good===1 && wrap_delta===16'd781,"Gray counter modulo wrap qualifies");
        // Low/high out-of-band samples; two consecutive valid windows needed.
        wrap_sample(16'd1726);check(wrap_good===0,"frequency too low rejected");
        wrap_sample(16'd2586);check(wrap_good===0,"frequency too high rejected");
        wrap_sample(16'd3367);check(wrap_good===0,"single valid window insufficient");
        wrap_sample(16'd4148);check(wrap_good===1,"second valid window qualifies");
        $display("[TB_INFO] Simulation Finished! checks=%0d",checks);$finish;
    end
    initial begin #6000000;$fatal(1,"[TB_ERROR] fault test timeout");end
endmodule
