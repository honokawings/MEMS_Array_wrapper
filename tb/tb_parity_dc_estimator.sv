`timescale 1ns/1ps
// Independent integer oracle: accumulate external accepted input samples;
// never use DUT training counters, memory, tags, or calculated offsets.
module tb_parity_dc_estimator;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,enable=0,valid_i=0,cfg_valid=0,bypass=0;
    reg [4095:0] data_i=0;
    reg [23:0] even_gain_q22=4194304,odd_gain_q22=4194304;
    wire cfg_ready,cfg_error_o,valid_o,clip_o,overrun_o,dc_ready_o;
    wire [127:0] dc_rejected_o;
    wire [23:0] active_even_gain_q22,active_odd_gain_q22;
    wire [4095:0] data_o;
    pcm_parity_compensation #(.DC_ESTIMATE_LOG2(12),.DC_SKIP_FRAMES(96)) dut(.*);
    longint signed sums[0:127],half_means[0:127],offsets[0:127],samples[0:127];
    bit rail_seen[0:127];
    reg [127:0] rejected_reference=0;
    integer c,f,n,cycles=0,capture_cycle,checks=0,frames=0;
    longint signed mean,deviation,full_product,expected;
    wire [127:0] parameter_done;
    wire [31:0] parameter_checks[0:127];
    genvar pc;
    generate for(pc=0;pc<128;pc++)begin:g_parameter
        parity_dc_parameter_case #(.CHANNELS(pc+1)) test(.clk(clk),.done(parameter_done[pc]),.checks(parameter_checks[pc]));
    end endgenerate
    always @(posedge clk)cycles<=cycles+1;
    function automatic longint signed round_away(input longint signed x,input integer shift);
        longint signed bias;
        begin bias=64'sd1 << (shift-1);round_away=x<0?-((-x+bias)>>>shift):((x+bias)>>>shift);end
    endfunction
    task check(input bit okay,input string detail);
        begin checks++;if(!okay)$fatal(1,"[TB_ERROR] DC128 %s at %0t",detail,$time);end
    endtask
    task configure(input [23:0] eg,input [23:0] og);
        begin
            @(negedge clk);check(cfg_ready,"gain queue unexpectedly occupied");
            even_gain_q22=eg;odd_gain_q22=og;cfg_valid=1;
            @(negedge clk);cfg_valid=0;
        end
    endtask
    task launch;
        begin
            for(c=0;c<128;c++)data_i[c*32 +:32]=samples[c][31:0];
            @(negedge clk);valid_i=1;
            @(negedge clk);valid_i=0;capture_cycle=cycles;
            // Captured frame must be independent of live upstream bus.
            data_i='0;
        end
    endtask
    task verify(input bit apply_dc,input [23:0] eg,input [23:0] og);
        begin
            n=0;while(!valid_o && n<140)begin @(negedge clk);n++;end
            check(valid_o,"frame timeout");check(cycles-capture_cycle==131,"latency must remain exactly131 cycles");
            for(c=0;c<128;c++)begin
                full_product=(samples[c]-(apply_dc?offsets[c]:0))*longint'(c%2?og:eg);
                expected=round_away(full_product,22);
                if(expected>64'sd2147483647)expected=64'sd2147483647;
                if(expected < -64'sd2147483648)expected=-64'sd2147483648;
                check($signed(data_o[c*32 +:32])===expected,
                    $sformatf("frame%0d channel%0d input%0d offset%0d got%0d expected%0d",frames,c,samples[c],apply_dc?offsets[c]:0,$signed(data_o[c*32 +:32]),expected));
            end
            frames++;@(negedge clk);check(!valid_o,"output valid lasted multiple cycles");
        end
    endtask
    initial begin
        for(c=0;c<128;c++)begin sums[c]=0;half_means[c]=0;offsets[c]=0;rail_seen[c]=0;samples[c]=1073741824;end
        repeat(3)@(negedge clk);rst_n=1;enable=1;
        // Startup BIST frames must consume neither skip nor training samples.
        bypass=1;
        repeat(3)begin launch();verify(0,4194304,4194304);check(!dc_ready_o,"BIST incorrectly completed training");end
        bypass=0;
        for(f=0;f<96;f++)begin
            for(c=0;c<128;c++)samples[c]=(f%2)?-1073741824:1073741824;
            launch();verify(0,4194304,4194304);check(!dc_ready_o,"skip frames incorrectly counted as training");
        end
        for(f=0;f<4096;f++)begin
            // Estimate the pre-gain raw signal even while the externally
            // selected gain mutes it or changes at a frame boundary.
            if(f==2048)configure(0,0);
            if(f==3072)configure(2097152,6291456);
            // A BIST interlude within training may not advance the window or
            // insert rail failures, even if bypass changes later in the frame.
            if(f==1024)begin
                for(c=0;c<128;c++)samples[c]=-1073741824;
                bypass=1;launch();repeat(19)@(negedge clk);bypass=0;
                verify(0,4194304,4194304);check(!dc_ready_o,"mid-window BIST advanced estimator");
            end
            for(c=0;c<128;c++)begin
                samples[c]=(c%2?-1:1)*(1000000+c*1003)+(f%2?-1:1)*(100+c*17);
                case(c)
                    2,3:samples[c]=-1073741824;
                    4:samples[c]=33554433;
                    5:samples[c]=(f<2048)?0:1073842;
                    6:samples[c]=(f==0)?1073741824:0;
                    8:samples[c]=33554432;
                    9:samples[c]=-33554432;
                    10:samples[c]=(f<2048)?0:1073742;
                    14:samples[c]=(f<2048)?0:1;
                    15:samples[c]=(f<2048)?0:-1;
                    16:samples[c]=(f<2048 && f%2)?-1:0;
                endcase
                sums[c]+=samples[c];
                rail_seen[c]|=(samples[c]>=1073741824 || samples[c]<=-1073741824);
                if(f==2047)half_means[c]=round_away(sums[c],11);
                if(f==4095)begin
                    mean=round_away(sums[c],12);deviation=mean-half_means[c];
                    rejected_reference[c]=rail_seen[c] || mean>33554432 || mean < -33554432 || deviation>536871 || deviation < -536871;
                    offsets[c]=rejected_reference[c]?0:mean;
                end
            end
            launch();verify(0,f<2048?4194304:f<3072?0:2097152,
                             f<2048?4194304:f<3072?0:6291456);
            check(dc_ready_o===(f==4095),$sformatf("training readiness wrong at real frame%0d",f));
        end
        configure(4194304,4194304);
        check(dc_rejected_o===rejected_reference,"per-channel rejection differs from independent oracle");
        check(dc_rejected_o[2] && dc_rejected_o[3] && dc_rejected_o[4] && dc_rejected_o[5] && dc_rejected_o[6],"directed rail/limit/stability failures did not reject");
        check(!dc_rejected_o[8] && !dc_rejected_o[9] && !dc_rejected_o[10],"inclusive offset/stability bounds rejected valid cases");
        check(offsets[14]==1 && offsets[15]==-1 && offsets[16]==0,"signed mean rounding oracle vectors wrong");
        // Frozen means must not chase changing sound or new input DC.
        for(f=0;f<8;f++)begin
            for(c=0;c<128;c++)samples[c]=(c%2?-1:1)*(15000000+c*173)+f*137;
            samples[2]=-1073741824;samples[3]=-1073741824;
            launch();verify(1,4194304,4194304);
            check(dc_rejected_o===rejected_reference && dc_ready_o,"frozen estimate/mask changed");
        end
        // Two exact widened-difference cases distinguish this design from
        // an incorrect sat32(x-DC) before the sub-unity multiplication.
        configure(2097152,3145728);
        for(c=0;c<128;c++)samples[c]=(c%2)?64'sd2147483647:-64'sd2147483648;
        launch();verify(1,2097152,3145728);
        check(!clip_o,"sub-unity widened differences spuriously clipped");
        // All gains zero gives exact zeros, including rejected raw rails.
        configure(0,0);launch();verify(1,0,0);
        configure(7340032,7340032);launch();verify(1,7340032,7340032);
        check(clip_o,"post-multiply overflow not reported");
        configure(2097152,6291456);
        for(c=0;c<128;c++)samples[c]=1000+c*3003;
        launch();repeat(19)@(negedge clk);bypass=1;verify(1,2097152,6291456);
        launch();repeat(19)@(negedge clk);bypass=0;verify(0,4194304,4194304);
        launch();verify(1,2097152,6291456);
        check(dc_ready_o && dc_rejected_o===rejected_reference,"BIST changed frozen estimate");
        // Disable/reset must abandon training and all frozen validity state.
        enable=0;@(negedge clk);check(!dc_ready_o && dc_rejected_o==0 && data_o==0 && !valid_o && !clip_o,"disable failed to clear estimate/pipe");
        enable=1;launch();repeat(129)@(negedge clk);rst_n=0;
        repeat(3)@(negedge clk);rst_n=1;
        repeat(135)begin @(negedge clk);check(!valid_o && !dc_ready_o && dc_rejected_o==0,"reset leaked old frame/estimate");end
        wait(&parameter_done);
        for(c=0;c<128;c++)checks+=parameter_checks[c];
        $display("[TB_DATA] DC real skip96+4096frames; exact means/signed ties, freeze, cap/stability/rail rejection, BIST/frame-atomic bypass, widened sub-unity multiply, gainzero, reset PASS");
        $display("[TB_DATA] DC CHANNELS1..128 accelerated windows, partial banks, disable/retrain, overrun rejection PASS");
        $display("[TB_DATA] DC checks=%0d full128frames=%0d latency131 PASS",checks,frames);
        $display("[TB_INFO] Simulation Finished!");$finish;
    end
    initial begin #10000000;$fatal(1,"[TB_ERROR] DC estimator test timeout");end
endmodule

module parity_dc_parameter_case #(parameter integer CHANNELS=1)(input wire clk,output reg done=0,output integer checks=0);
    reg rst_n=0,enable=0,valid_i=0,cfg_valid=0,bypass=0;
    reg [CHANNELS*32-1:0] data_i=0;
    reg [23:0] even_gain_q22=4194304,odd_gain_q22=4194304;
    wire cfg_ready,cfg_error_o,valid_o,clip_o,overrun_o,dc_ready_o;
    wire [CHANNELS-1:0] dc_rejected_o;
    wire [23:0] active_even_gain_q22,active_odd_gain_q22;
    wire [CHANNELS*32-1:0] data_o;
    pcm_parity_compensation #(.CHANNELS(CHANNELS),.DC_ESTIMATE_LOG2(2),.DC_SKIP_FRAMES(2)) dut(.*);
    longint signed samples[0:CHANNELS-1],offsets[0:CHANNELS-1],p,e;
    integer c,f,n,cycles=0,capture_cycle;
    always @(posedge clk)cycles<=cycles+1;
    task check(input bit okay,input string detail);
        begin checks++;if(!okay)$fatal(1,"[TB_ERROR] DC CHANNELS%0d %s at%0t",CHANNELS,detail,$time);end
    endtask
    task launch;
        begin
            for(c=0;c<CHANNELS;c++)data_i[c*32 +:32]=samples[c][31:0];
            @(negedge clk);valid_i=1;@(negedge clk);valid_i=0;capture_cycle=cycles;data_i=0;
        end
    endtask
    task verify(input bit apply_dc,input bit muted);
        begin
            n=0;while(!valid_o && n<CHANNELS+6)begin @(negedge clk);n++;end
            check(valid_o && cycles-capture_cycle==CHANNELS+3,"latency/frame completion incorrect");
            for(c=0;c<CHANNELS;c++)begin
                p=(samples[c]-(apply_dc?offsets[c]:0))*(muted?0:4194304);
                e=p<0?-((-p+2097152)>>>22):((p+2097152)>>>22);
                if(e>2147483647)e=2147483647;if(e < -64'sd2147483648)e=-64'sd2147483648;
                check($signed(data_o[c*32 +:32])===e,$sformatf("c%0d got%0d expected%0d",c,$signed(data_o[c*32 +:32]),e));
            end
            @(negedge clk);check(!valid_o,"valid pulse incorrect");
        end
    endtask
    task train(input integer base,input bit overlap);
        begin
            for(f=0;f<6;f++)begin
                for(c=0;c<CHANNELS;c++)begin offsets[c]=(c%2?-1:1)*(base+CHANNELS*31+c*47);samples[c]=offsets[c]+(f%2?-7:7);end
                launch();
                if(overlap && f==2)begin
                    repeat(CHANNELS)@(negedge clk);valid_i=1;@(negedge clk);valid_i=0;
                end
                verify(0,0);check(dc_ready_o===(f==5),"skip/train count wrong");
            end
            check(dc_rejected_o===(overlap?{CHANNELS{1'b1}}:{CHANNELS{1'b0}}),"final rejected mask incorrect");
        end
    endtask
    initial begin
        repeat(3)@(negedge clk);rst_n=1;enable=1;
        for(c=0;c<CHANNELS;c++)begin samples[c]=1073741824;offsets[c]=0;end
        bypass=1;launch();verify(0,0);check(!dc_ready_o,"bypass advanced DC state");bypass=0;
        train(300000,0);
        for(c=0;c<CHANNELS;c++)samples[c]=offsets[c]+13;
        launch();verify(1,0);
        // Abort the populated pipeline, then retrain over stale physical RAM.
        launch();@(negedge clk);enable=0;@(negedge clk);
        check(data_o==0 && !valid_o && !dc_ready_o && dc_rejected_o==0,"disable abort left state");
        repeat(CHANNELS+6)begin @(negedge clk);check(!valid_o,"disabled frame leaked");end
        enable=1;
        // Partially overwrite a new training frame, then synchronously reset.
        // The next first training frame must reseed every physical RAM row.
        for(f=0;f<2;f++)begin launch();verify(0,0);end
        launch();repeat(CHANNELS/2+1)@(negedge clk);rst_n=0;
        @(negedge clk);check(!valid_o && !dc_ready_o && dc_rejected_o==0 && data_o==0,"mid-training reset retained state");rst_n=1;
        repeat(CHANNELS+6)begin @(negedge clk);check(!valid_o,"reset training frame leaked");end
        train(1700000,0);
        for(c=0;c<CHANNELS;c++)samples[c]=offsets[c]-11;
        launch();verify(1,0);
        // A rejected overlapping real frame invalidates the complete window,
        // so a truncated stream cannot masquerade as valid calibration.
        rst_n=0;@(negedge clk);rst_n=1;train(500000,1);
        for(c=0;c<CHANNELS;c++)samples[c]=offsets[c]+29;
        launch();verify(0,0);check(overrun_o,"overlap not reported");
        // Existing gain configuration still works after DC rejection.
        enable=0;@(negedge clk);even_gain_q22=0;odd_gain_q22=0;cfg_valid=1;
        @(negedge clk);cfg_valid=0;enable=1;launch();verify(0,1);
        check(!dc_ready_o && dc_rejected_o==0,"new acquisition retained old estimate");
        done=1;
    end
endmodule
