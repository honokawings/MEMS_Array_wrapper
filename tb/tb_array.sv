`timescale 1ns/1ps
module tb_array;
    localparam integer N=16384,FRAMES=N/64,STARTUP=8,SETTLE=96;
    reg clk=0;always #4.0690104167 clk=~clk;
    reg rst_n=0,enable=0,cfg_valid=0;
    reg [6:0] cfg_channel=0;
    reg signed [23:0] cfg_gain=0;
    reg signed [31:0] cfg_offset=0;
    wire cfg_ready,mic_clk,started;
    tri [63:0] pdm_data;
    reg [63:0] high_driver='z,low_driver='z;
    assign pdm_data=high_driver;assign pdm_data=low_driver;
    wire signed [23:0] pcm_data;
    wire [6:0] pcm_channel;
    wire [63:0] pcm_frame_id;
    wire pcm_valid,pcm_first,pcm_last,overflow,processing_error,clipped;
    wire [31:0] dropped_frames;
    reg pcm_ready=0;
    mems_array_top #(.STARTUP_CYCLES(STARTUP),.SETTLE_FRAMES(SETTLE)) dut(
        .clk(clk),.rst_n(rst_n),.enable(enable),.pdm_data(pdm_data),.mic_clk(mic_clk),.started(started),
        .cfg_valid(cfg_valid),.cfg_channel(cfg_channel),.cfg_gain(cfg_gain),.cfg_offset(cfg_offset),.cfg_ready(cfg_ready),
        .pcm_data(pcm_data),.pcm_channel(pcm_channel),.pcm_frame_id(pcm_frame_id),
        .pcm_valid(pcm_valid),.pcm_first(pcm_first),.pcm_last(pcm_last),.pcm_ready(pcm_ready),
        .overflow(overflow),.dropped_frames(dropped_frames),.processing_error(processing_error),.clipped(clipped),
        .parity_cfg_valid(1'b0),.parity_even_gain(24'd4194304),.parity_odd_gain(24'd4194304),
        .parity_cfg_ready(),.parity_active_even_gain(),.parity_active_odd_gain(),.parity_bypass(1'b0));
    reg [127:0] pdm[0:N-1];
    reg [4095:0] exp_cic[0:N/8-1],exp_fir1[0:N/32-1],exp_fir2[0:FRAMES-1];
    reg [3071:0] exp_pcm[0:FRAMES-1];
    reg [55:0] cal[0:127];
    integer raw_period=-1,input_count=0,cic_count=0,f1_count=0,f2_count=0;
    integer pcm_count=0,expected_frame=SETTLE,expected_channel=0,epoch;
    integer cycle=0,last_cic=-1,last_f1=-1,last_f2=-1;
    reg [31:0] rng=32'h713579ab;
    reg stalled=0;
    reg [97:0] held;
    function automatic [63:0] phase_bits(input integer period,input bit odd);
        integer c,idx;
        begin
            idx=period-STARTUP;
            for(c=0;c<64;c=c+1)
                phase_bits[c]=(idx>=0 && idx<N)?pdm[idx][2*c+odd]:(period%2);
        end
    endfunction
    always @(negedge enable) raw_period=-1;
    // 100ns maximum tDV + 20ns board budget, with a true floating LR bus.
    always @(posedge mic_clk) begin
        raw_period=raw_period+1;low_driver<=#30 'z;
        high_driver<=#120 phase_bits(raw_period,1);
    end
    always @(negedge mic_clk) begin
        high_driver<=#30 'z;low_driver<=#120 phase_bits(raw_period,0);
    end
    always @(negedge clk) begin
        rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
        pcm_ready=enable && (rng[3:0]!=0) && (rng[7:4]!=0);
    end
    always @(posedge clk) begin
        if(!rst_n || !enable) begin
            input_count=0;cic_count=0;f1_count=0;f2_count=0;
            pcm_count=0;expected_frame=SETTLE;expected_channel=0;stalled=0;
            cycle=0;last_cic=-1;last_f1=-1;last_f2=-1;
        end else begin
            cycle=cycle+1;
            if(dut.bits_valid && input_count<N) begin
                if(dut.bits!==pdm[input_count]) $fatal(1,"[TB_ERROR] PDM period=%0d",input_count);
                input_count=input_count+1;
            end
            if(dut.cic_valid && cic_count<N/8) begin
                if(last_cic>=0 && cycle-last_cic!=320) $fatal(1,"[TB_ERROR] CIC cadence");
                last_cic=cycle;
                if(dut.cic_data!==exp_cic[cic_count]) $fatal(1,"[TB_ERROR] CIC frame=%0d",cic_count);
                cic_count=cic_count+1;
            end
            if(dut.fir1_valid && f1_count<N/32) begin
                if(last_f1>=0 && cycle-last_f1!=1280) $fatal(1,"[TB_ERROR] FIR1 cadence");
                last_f1=cycle;
                if(dut.fir1_data!==exp_fir1[f1_count]) $fatal(1,"[TB_ERROR] FIR1 frame=%0d",f1_count);
                f1_count=f1_count+1;
            end
            if(dut.fir2_valid && f2_count<FRAMES) begin
                if(last_f2>=0 && cycle-last_f2!=2560) $fatal(1,"[TB_ERROR] FIR2 cadence");
                last_f2=cycle;
                if(dut.fir2_data!==exp_fir2[f2_count]) $fatal(1,"[TB_ERROR] FIR2 frame=%0d",f2_count);
                f2_count=f2_count+1;
            end
            if(stalled && {pcm_valid,pcm_frame_id,pcm_channel,pcm_first,pcm_last,pcm_data}!==held)
                $fatal(1,"[TB_ERROR] Output changed while stalled");
            stalled=pcm_valid && !pcm_ready;
            held={pcm_valid,pcm_frame_id,pcm_channel,pcm_first,pcm_last,pcm_data};
            if(pcm_valid && pcm_ready && expected_frame<FRAMES) begin
                if(pcm_frame_id!==expected_frame || pcm_channel!==expected_channel ||
                   pcm_first!==(expected_channel==0) || pcm_last!==(expected_channel==127))
                    $fatal(1,"[TB_ERROR] PCM ordering frame=%0d channel=%0d",pcm_frame_id,pcm_channel);
                if(pcm_data!==exp_pcm[expected_frame][expected_channel*24 +: 24])
                    $fatal(1,"[TB_ERROR] PCM mismatch frame=%0d ch=%0d got=%0d expected=%0d",
                        expected_frame,expected_channel,pcm_data,
                        $signed(exp_pcm[expected_frame][expected_channel*24 +: 24]));
                pcm_count=pcm_count+1;
                if(expected_channel==127) begin expected_channel=0;expected_frame=expected_frame+1;end
                else expected_channel=expected_channel+1;
            end
            if(processing_error || overflow || dropped_frames!=0)
                $fatal(1,"[TB_ERROR] Unexpected overrun/overflow");
        end
    end
    property stable_when_stalled;
        @(posedge clk) disable iff(!rst_n || !enable)
        pcm_valid && !pcm_ready |=> $stable({pcm_valid,pcm_data,pcm_channel,pcm_frame_id,pcm_first,pcm_last});
    endproperty
    assert property(stable_when_stalled) else $fatal(1,"[TB_ERROR] Output hold assertion");
    task automatic configure;
        integer c;
        begin
            for(c=0;c<128;c=c+1) begin
                @(negedge clk);cfg_valid=1;cfg_channel=c;
                cfg_gain=cal[c][55:32];cfg_offset=cal[c][31:0];
                if(!cfg_ready) $fatal(1,"[TB_ERROR] Configuration unavailable while disabled");
            end
            @(negedge clk);cfg_valid=0;
        end
    endtask
    initial begin
        $readmemh("../tb/vectors/pdm.hex",pdm);
        $readmemh("../tb/vectors/expected_cic.hex",exp_cic);
        $readmemh("../tb/vectors/expected_fir1.hex",exp_fir1);
        $readmemh("../tb/vectors/expected_fir2.hex",exp_fir2);
        $readmemh("../tb/vectors/expected_pcm.hex",exp_pcm);
        $readmemh("../tb/vectors/calibration.hex",cal);
        repeat(5) @(negedge clk);rst_n=1;
        configure();
        for(epoch=0;epoch<2;epoch=epoch+1) begin
            @(negedge clk);enable=1;
            $display("[TB_MONITOR] acquisition epoch %0d",epoch);
            repeat(1000) @(negedge clk);
            cfg_valid=1;cfg_channel=8;cfg_gain=0;cfg_offset=32'h7fffffff;
            if(cfg_ready) $fatal(1,"[TB_ERROR] cfg_ready asserted while enabled");
            @(negedge clk);cfg_valid=0;
            wait(expected_frame==FRAMES);@(negedge clk);
            if(input_count!=N || cic_count!=N/8 || f1_count!=N/32 || f2_count!=FRAMES || !clipped)
                $fatal(1,"[TB_ERROR] Incomplete scoreboards or missing saturation flag");
            $display("[TB_DATA] epoch=%0d CIC=%0d FIR1=%0d FIR2=%0d PCM=%0d, all channels exact",
                epoch,cic_count*128,f1_count*128,f2_count*128,pcm_count);
            enable=0;repeat(20) @(negedge clk);
            if(pcm_valid || mic_clk || started) $fatal(1,"[TB_ERROR] Stop did not flush acquisition");
        end
        enable=1;repeat(1800) @(negedge clk);rst_n=0;enable=0;
        repeat(4) @(negedge clk);
        if(pcm_valid || processing_error || overflow) $fatal(1,"[TB_ERROR] Reset did not clear state");
        $display("[TB_INFO] Simulation Finished!");$finish;
    end
    initial begin #20_000_000;$fatal(1,"[TB_ERROR] Watchdog");end
endmodule
