`timescale 1ns/1ps
module tb_parity_compensation;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,enable=0,valid_i=0,cfg_valid=0,bypass=0;
    reg [4095:0] data_i=0;
    reg [23:0] even_gain_q22=4194304,odd_gain_q22=4194304;
    wire cfg_ready,cfg_error_o,valid_o,clip_o,overrun_o;
    wire [23:0] active_even_gain_q22,active_odd_gain_q22;
    wire [4095:0] data_o;
    wire dc_ready_o;
    wire [127:0] dc_rejected_o;
    pcm_parity_compensation dut(.*);
    integer checks=0,frames=0,c,n,cycle_count=0,frame_capture_cycle=0;
    integer boundary_checks=0,parameter_check_total=0;
    reg directed_boundaries=0;
    wire [127:0] parameter_done;
    wire [31:0] parameter_checks[0:127];
    genvar parameter_case;
    generate for(parameter_case=0;parameter_case<128;parameter_case=parameter_case+1)begin:g_parameter
        parity_parameter_case #(.CHANNELS(parameter_case+1)) test(
            .clk(clk),.done(parameter_done[parameter_case]),.checks(parameter_checks[parameter_case]));
    end endgenerate
    always @(posedge clk)cycle_count<=cycle_count+1;
    reg signed [31:0] sample[0:127];
    longint signed product_reference,expected;
    task check(input bit okay,input string why);
        begin
            checks=checks+1;
            if(!okay)$fatal(1,"[TB_ERROR] %s time=%0t",why,$time);
        end
    endtask
    task configure(input reg [23:0] eg,input reg [23:0] og);
        begin
            @(negedge clk);check(cfg_ready,"configuration queue unexpectedly full");
            cfg_valid=1;even_gain_q22=eg;odd_gain_q22=og;
            @(negedge clk);cfg_valid=0;
        end
    endtask
    task pulse_frame;
        begin
            @(negedge clk);valid_i=1;
            @(negedge clk);valid_i=0;frame_capture_cycle=cycle_count;
        end
    endtask
    task verify_frame(input reg [23:0] eg,input reg [23:0] og);
        begin
            n=0;
            while(!valid_o && n<2560) begin @(negedge clk);n=n+1;end
            check(valid_o,"frame exceeded 2560-cycle budget");
            check(cycle_count-frame_capture_cycle==131,"128-channel capture-to-output latency must be 131 cycles");
            for(c=0;c<128;c=c+1) begin
                product_reference=longint'(sample[c])*longint'(c%2?og:eg);
                expected=product_reference<0? -((-product_reference+2097152)>>>22):
                                                ((product_reference+2097152)>>>22);
                if(expected>64'sd2147483647)expected=64'sd2147483647;
                if(expected < -64'sd2147483648)expected=-64'sd2147483648;
                check($signed(data_o[c*32 +: 32])===expected,
                      $sformatf("channel%0d got=%0d expected=%0d",c,$signed(data_o[c*32 +: 32]),expected));
                if(directed_boundaries && (c==15 || c==16 || c==31 || c==32 || c==111 || c==112 || c==127))begin
                    boundary_checks++;
                    $display("[TB_DATA] group boundary channel=%0d unique_input=%0d output=%0d expected=%0d PASS",
                        c,sample[c],$signed(data_o[c*32 +: 32]),expected);
                end
            end
            frames=frames+1;
            $display("[TB_DATA] parity frame=%0d eg=%0d og=%0d latency_remaining=%0d total_latency=%0d PASS",frames,eg,og,n,cycle_count-frame_capture_cycle);
            @(negedge clk);check(!valid_o,"valid_o must be one-cycle pulse");
        end
    endtask
    task abort_pipeline(input bit reset_pipeline,input integer cycles_after_capture);
        integer pause_cycle;
        begin
            pulse_frame();repeat(cycles_after_capture)@(negedge clk);
            check(!valid_o,"abort must occur before the completed-frame pulse");
            if(reset_pipeline)rst_n=0;else enable=0;
            @(negedge clk);
            check(data_o===4096'b0 && !valid_o && !clip_o && !overrun_o,"abort failed to clear output/flags");
            for(pause_cycle=0;pause_cycle<135;pause_cycle++)begin
                @(negedge clk);check(!valid_o,"aborted pipeline produced a stale frame while cleared");
            end
            if(reset_pipeline)rst_n=1;else enable=1;
            for(pause_cycle=0;pause_cycle<135;pause_cycle++)begin
                @(negedge clk);check(!valid_o,"aborted pipeline produced a stale frame after re-enable");
            end
            check(cfg_ready,"abort left stale pending configuration");
            if(reset_pipeline)begin
                check(active_even_gain_q22==4194304 && active_odd_gain_q22==4194304,"in-flight reset did not restore unity");
                pulse_frame();verify_frame(4194304,4194304);
            end else begin
                check(active_even_gain_q22==3145728 && active_odd_gain_q22==5242880,"in-flight disable lost retained gains");
                pulse_frame();verify_frame(3145728,5242880);
            end
            $display("[TB_DATA] pipeline abort reset=%0d cycles_after_capture=%0d flush/restart PASS",reset_pipeline,cycles_after_capture);
        end
    endtask
    initial begin
        for(c=0;c<128;c=c+1) begin
            case((c/2)%8)
                0:sample[c]=1;
                1:sample[c]=-1;
                2:sample[c]=3;
                3:sample[c]=-3;
                4:sample[c]=32'h7fffffff;
                5:sample[c]=32'h80000000;
                6:sample[c]=123456789;
                7:sample[c]=-123456789;
            endcase
            data_i[c*32 +: 32]=sample[c];
        end
        repeat(3)@(negedge clk);rst_n=1;
        check(active_even_gain_q22==4194304 && active_odd_gain_q22==4194304,"reset gains not unity");
        configure(2097152,6291456);
        check(active_even_gain_q22==2097152 && active_odd_gain_q22==6291456,"disabled configuration not committed");
        enable=1;pulse_frame();
        // New coefficients and bypass arrive while an old frame is processing.
        // Every channel of that frame must still use the latched old gains.
        repeat(30)@(negedge clk);configure(1048576,7340032);bypass=1;
        check(!cfg_ready,"pending configuration not held until boundary");
        check(active_even_gain_q22==2097152 && active_odd_gain_q22==6291456,"midframe configuration became active");
        @(negedge clk);valid_i=1;@(negedge clk);valid_i=0;
        verify_frame(2097152,6291456);
        check(clip_o && overrun_o,"clipping or overlap not reported");
        check(!cfg_ready,"pending configuration committed without frame boundary");
        pulse_frame();verify_frame(4194304,4194304);
        check(cfg_ready && active_even_gain_q22==1048576 && active_odd_gain_q22==7340032,"bypass lost pending configuration");
        bypass=0;pulse_frame();verify_frame(1048576,7340032);
        // Request and input valid on exactly the same edge use the new pair.
        @(negedge clk);cfg_valid=1;even_gain_q22=0;odd_gain_q22=8388607;valid_i=1;
        @(negedge clk);cfg_valid=0;valid_i=0;frame_capture_cycle=cycle_count;
        verify_frame(0,8388607);
        check(active_even_gain_q22==0 && active_odd_gain_q22==8388607,"same-boundary request not active");
        configure(24'h800000,4194304);
        check(cfg_error_o,"negative even gain was not rejected");
        check(active_even_gain_q22==0 && active_odd_gain_q22==8388607 && cfg_ready,"invalid config changed state");
        configure(4194304,24'hffffff);
        check(cfg_error_o,"negative odd gain was not rejected");
        pulse_frame();verify_frame(0,8388607);
        // Disable commits pending coefficients and clears only data flags.
        configure(3145728,5242880);check(!cfg_ready,"idle enabled request not queued");
        @(negedge clk);enable=0;
        @(negedge clk);check(cfg_ready && active_even_gain_q22==3145728 && active_odd_gain_q22==5242880,"disable did not commit queued gains");
        check(!clip_o && !overrun_o && !valid_o,"disable failed to clear stream flags");
        bypass=1;enable=1;pulse_frame();verify_frame(4194304,4194304);
        bypass=0;pulse_frame();verify_frame(3145728,5242880);
        // Reset discards pending updates and restores the explicit defaults.
        configure(1,2);@(negedge clk);rst_n=0;
        repeat(3)@(negedge clk);rst_n=1;
        check(cfg_ready && active_even_gain_q22==4194304 && active_odd_gain_q22==4194304,"reset left stale gains");
        pulse_frame();verify_frame(4194304,4194304);
        // Original corner vectors repeat every 16 channels. Unique signed
        // values make crossed groups/tags detectable by the arithmetic model.
        for(c=0;c<128;c=c+1)begin
            sample[c]=(c%2 ? -1 : 1)*(12345+c*17011);
            data_i[c*32 +: 32]=sample[c];
        end
        configure(3145728,5242880);directed_boundaries=1;pulse_frame();
        // The whole input frame must stay captured while banks are reading it.
        data_i=0;verify_frame(3145728,5242880);directed_boundaries=0;
        check(boundary_checks==7,"directed group-boundary coverage incomplete");
        for(c=0;c<128;c=c+1)data_i[c*32 +: 32]=sample[c];
        // Both a filled early pipe and the final bank-selection drain are
        // interrupted; no partial frame may escape after reset/disable.
        abort_pipeline(0,1);abort_pipeline(0,128);
        abort_pipeline(1,1);abort_pipeline(1,128);
        wait(&parameter_done);
        for(c=0;c<128;c=c+1)parameter_check_total+=parameter_checks[c];
        $display("[TB_DATA] parameter CHANNELS=1..128, partial-bank padding and drain-overrun checks=%0d PASS",parameter_check_total);
        $display("[TB_DATA] frames=%0d channels_checked=%0d checks=%0d parameter_checks=%0d total_checks=%0d; positive/negative ties, saturation, atomic cfg, bypass, overrun, boundaries and aborts PASS",
            frames,frames*128,checks,parameter_check_total,checks+parameter_check_total);
        $display("[TB_INFO] Simulation Finished!");$finish;
    end
    initial begin #200000;$fatal(1,"[TB_ERROR] parity test timeout");end
endmodule

// Every legal CHANNELS value exercises both a same-edge config/frame capture
// and a second gain pair, with a distinct per-channel external reference.
module parity_parameter_case #(parameter integer CHANNELS=1)(input wire clk,output reg done=0,output integer checks=0);
    reg rst_n=0,enable=0,valid_i=0,cfg_valid=0,bypass=0;
    reg [CHANNELS*32-1:0] data_i=0;
    reg [23:0] even_gain_q22=2097152,odd_gain_q22=5242880;
    wire cfg_ready,cfg_error_o,valid_o,clip_o,overrun_o;
    wire [23:0] active_even_gain_q22,active_odd_gain_q22;
    wire [CHANNELS*32-1:0] data_o;
    wire dc_ready_o;
    wire [CHANNELS-1:0] dc_rejected_o;
    reg signed [31:0] samples[0:CHANNELS-1];
    integer c,n,cycles=0,capture_cycle;
    longint signed full_product,rounded_expected;
    pcm_parity_compensation #(.CHANNELS(CHANNELS)) dut(.*);
    always @(posedge clk)cycles<=cycles+1;
    task check(input bit okay,input string detail);
        begin checks++;if(!okay)$fatal(1,"[TB_ERROR] CHANNELS=%0d %s at %0t",CHANNELS,detail,$time);end
    endtask
    task verify(input [23:0] eg,input [23:0] og);
        begin
            n=0;while(!valid_o && n<2560)begin @(negedge clk);n++;end
            check(valid_o,"frame timeout");
            check(cycles-capture_cycle==CHANNELS+3,"capture-to-output latency differs from CHANNELS+3");
            for(c=0;c<CHANNELS;c++)begin
                full_product=longint'(samples[c])*longint'(c%2?og:eg);
                rounded_expected=full_product<0 ? -((-full_product+2097152)>>>22) : ((full_product+2097152)>>>22);
                if(rounded_expected>64'sd2147483647)rounded_expected=64'sd2147483647;
                if(rounded_expected < -64'sd2147483648)rounded_expected=-64'sd2147483648;
                check($signed(data_o[c*32 +: 32])===rounded_expected,$sformatf("channel=%0d got=%0d expected=%0d",c,$signed(data_o[c*32 +: 32]),rounded_expected));
            end
            @(negedge clk);check(!valid_o,"output pulse lasted more than one cycle");
        end
    endtask
    initial begin
        for(c=0;c<CHANNELS;c++)begin samples[c]=(c%2?-1:1)*(100003+CHANNELS*37+c*1907);data_i[c*32 +: 32]=samples[c];end
        repeat(3)@(negedge clk);rst_n=1;enable=1;
        @(negedge clk);valid_i=1;cfg_valid=1;
        @(negedge clk);valid_i=0;cfg_valid=0;capture_cycle=cycles;
        // Last bank is registered but the read/multiply pipe still owns the
        // frame. Especially CHANNELS=1 must not recapture at group_valid only.
        repeat(CHANNELS)@(negedge clk);valid_i=1;data_i='1;
        @(negedge clk);valid_i=0;
        verify(2097152,5242880);check(overrun_o,"drain-overlap input was not rejected");
        check(active_even_gain_q22==2097152 && active_odd_gain_q22==5242880,"same-edge configuration lost");
        enable=0;@(negedge clk);check(!overrun_o && !clip_o && !valid_o,"disable did not clear stream state");
        even_gain_q22=6291456;odd_gain_q22=3145728;cfg_valid=1;
        @(negedge clk);cfg_valid=0;
        for(c=0;c<CHANNELS;c++)begin samples[c]=(c%2?1:-1)*(200007+CHANNELS*41+c*2711);data_i[c*32 +: 32]=samples[c];end
        enable=1;valid_i=1;
        @(negedge clk);valid_i=0;capture_cycle=cycles;
        verify(6291456,3145728);
        check(cfg_ready && active_even_gain_q22==6291456 && active_odd_gain_q22==3145728,"retained second gain pair wrong");
        done=1;
    end
endmodule
