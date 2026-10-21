`timescale 1ns/1ps
// Actual FIR saturation cone + clocked writeback. Only arithmetic/control
// inputs are forced; no result, overflow or clip output is forced.
module tb_fir_round_sat;
    reg clk=0, rst_n=0;
    always #4 clk=~clk;
    reg signed [71:0] sample_value=0;
    reg write_enable=0;
    reg [2:0] selected_group=0;
    wire [255:0] data1,data2;
    wire valid1,valid2,clip1,clip2,overrun1,overrun2;
    fir_decimator #(.CHANNELS(8),.LANES(1),.COEFF_SET(1),.TAPS(63),.DEPTH(128)) dut1(
        .clk(clk),.rst_n(rst_n),.data_i(256'b0),.valid_i(1'b0),
        .data_o(data1),.valid_o(valid1),.overrun_o(overrun1),.clip_o(clip1));
    fir_decimator #(.CHANNELS(8),.LANES(1),.COEFF_SET(2),.TAPS(127),.DEPTH(256)) dut2(
        .clk(clk),.rst_n(rst_n),.data_i(256'b0),.valid_i(1'b0),
        .data_o(data2),.valid_o(valid2),.overrun_o(overrun2),.clip_o(clip2));
    reg [31:0] expected_groups[0:7];
    reg expected_clip=0;
    integer vectors=0,checks=0,cone_checks=0,writebacks=0;
    integer held_group_checks=0,clip_checks=0,valid_checks=0;
    integer reset_cycles=0,inhibit_cycles=0;
    integer literal_vectors=0,exhaustive_vectors=0,random_vectors=0,control_vectors=0;
    integer positive_clip_cases=0,negative_clip_cases=0,inrange_cases=0;
    integer half_tie_cases=0,wrap_cases=0;
    reg [7:0] group_seen_mask=0;
    integer h,l,f,i,g;
    reg [31:0] low_class[0:5];
    reg [29:0] fraction_class[0:2];
    reg [31:0] rng=32'ha12f7093,rand_a,rand_b,rand_c;
    reg signed [71:0] value;
    function automatic [31:0] next_random(input [31:0] old);
        reg [31:0] x;
        begin x=old^(old<<13);x=x^(x>>17);next_random=x^(x<<5);end
    endfunction
    task automatic reference(input signed [71:0] raw,
        output reg [31:0] pcm, output reg pos,output reg neg);
        reg signed [72:0] wide,magnitude,rounded_magnitude,restored;
        reg signed [41:0] wrapped;
        begin
            // One extra bit makes abs(signed72_MIN) and add-half safe.
            // Signed magnitude reference differs from DUT floor/prefix logic.
            wide={raw[71],raw};
            magnitude=(wide<0)?-wide:wide;
            rounded_magnitude=(magnitude+73'sd536870912)/73'sd1073741824;
            restored=(wide<0)?-rounded_magnitude:rounded_magnitude;
            // Existing FIR contract wraps at 42 bits before saturation.
            wrapped=restored[41:0];
            pos=wrapped>42'sd2147483647;
            neg=wrapped< -42'sd2147483648;
            pcm=pos?32'h7fffffff:neg?32'h80000000:wrapped[31:0];
        end
    endtask
    task automatic drive_sample(input signed [71:0] raw,input reg enabled,
        input [2:0] target,input reg reset_released);
        reg [31:0] pcm;
        reg pos,neg,expected_valid;
        integer k;
        begin
            @(negedge clk);
            sample_value=raw;write_enable=enabled;selected_group=target;rst_n=reset_released;
            reference(raw,pcm,pos,neg);
            #1;
            if({dut1.lane[0].result_overflow_pos,dut1.lane[0].result_overflow_neg,dut1.lane[0].saturated_result} !== {pos,neg,pcm})
                $fatal(1,"[TB_ERROR] coeff1 actual cone raw=%h got=%b/%b/%h ref=%b/%b/%h",raw,dut1.lane[0].result_overflow_pos,dut1.lane[0].result_overflow_neg,dut1.lane[0].saturated_result,pos,neg,pcm);
            if({dut2.lane[0].result_overflow_pos,dut2.lane[0].result_overflow_neg,dut2.lane[0].saturated_result} !== {pos,neg,pcm})
                $fatal(1,"[TB_ERROR] coeff2 actual cone raw=%h got=%b/%b/%h ref=%b/%b/%h",raw,dut2.lane[0].result_overflow_pos,dut2.lane[0].result_overflow_neg,dut2.lane[0].saturated_result,pos,neg,pcm);
            cone_checks=cone_checks+6;checks=checks+6;
            @(posedge clk);
            if(!reset_released) begin
                for(k=0;k<8;k=k+1)expected_groups[k]=0;
                expected_clip=0;reset_cycles=reset_cycles+1;
            end else if(enabled) begin
                expected_groups[target]=pcm;
                expected_clip=expected_clip || pos || neg;
                group_seen_mask=group_seen_mask | (8'b1<<target);
            end else inhibit_cycles=inhibit_cycles+1;
            expected_valid=reset_released && enabled && target==7;
            #1;
            for(k=0;k<8;k=k+1)begin
                if(dut1.lane[0].result[k*32+:32]!==expected_groups[k] || data1[k*32+:32]!==expected_groups[k])
                    $fatal(1,"[TB_ERROR] coeff1 write/hold group=%0d active=%0d en=%b reset=%b got=%h ref=%h",k,target,enabled,reset_released,data1[k*32+:32],expected_groups[k]);
                if(dut2.lane[0].result[k*32+:32]!==expected_groups[k] || data2[k*32+:32]!==expected_groups[k])
                    $fatal(1,"[TB_ERROR] coeff2 write/hold group=%0d active=%0d en=%b reset=%b got=%h ref=%h",k,target,enabled,reset_released,data2[k*32+:32],expected_groups[k]);
                checks=checks+4;
                if(reset_released && (!enabled || target!=k))held_group_checks=held_group_checks+2;
            end
            if(clip1!==expected_clip || clip2!==expected_clip)
                $fatal(1,"[TB_ERROR] sticky clip got=%b/%b ref=%b en=%b reset=%b",clip1,clip2,expected_clip,enabled,reset_released);
            if(valid1!==expected_valid || valid2!==expected_valid)
                $fatal(1,"[TB_ERROR] final_valid/group got=%b/%b ref=%b group=%0d",valid1,valid2,expected_valid,target);
            checks=checks+4;clip_checks=clip_checks+2;valid_checks=valid_checks+2;
            if(reset_released && enabled)writebacks=writebacks+2;
            if(pos)positive_clip_cases=positive_clip_cases+1;
            else if(neg)negative_clip_cases=negative_clip_cases+1;
            else inrange_cases=inrange_cases+1;
            if(raw[29:0]==30'd536870912)half_tie_cases=half_tie_cases+1;
            if(raw>=72'sh7fffffffffe0000000)wrap_cases=wrap_cases+1;
            vectors=vectors+1;
        end
    endtask
    task automatic control(input signed [71:0] raw,input reg enabled,input [2:0] target,input reg reset_released);
        begin drive_sample(raw,enabled,target,reset_released);control_vectors=control_vectors+1;end
    endtask
    initial begin
        force dut1.lane[0].final_sum=sample_value;
        force dut2.lane[0].final_sum=sample_value;
        force dut1.final_valid=write_enable;force dut2.final_valid=write_enable;
        force dut1.final_group=selected_group;force dut2.final_group=selected_group;
        for(g=0;g<8;g=g+1)expected_groups[g]=0;
        control(0,0,0,0);
        // Saturation while inhibited must neither write nor set clip.
        control(72'sh7fffffffffffffffff,0,7,1);
        control(72'sh800000000000000000,0,0,1);
        for(i=0;i<8;i=i+1)control((72'sd17+i)<<30,1,i[2:0],1);
        control(72'sh001fffffffe0000000,1,3,1);
        control(72'sd0,1,5,1); // positive clip remains sticky
        control(72'shffdfffffffe0000000,0,6,1);
        control(72'sh7fffffffffffffffff,1,7,0); // reset dominates enabled/last
        control(0,0,0,1); // no stale result/clip after reset
        control(72'shffdfffffffe0000000,1,6,1);
        control(72'sd1<<30,1,7,1); // negative clip remains sticky
        control(0,0,0,0);
        control(0,0,0,1);
        $display("[TB_MONITOR] actual cone/control checks completed; starting literal boundaries");
        drive_sample(72'hffffffffff5fffffff,1,3'd0,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffffffffff60000000,1,3'd1,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffffffffff60000001,1,3'd2,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffffffffff9fffffff,1,3'd3,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffffffffffa0000000,1,3'd4,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffffffffffa0000001,1,3'd5,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffffffffffdfffffff,1,3'd6,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffffffffffe0000000,1,3'd7,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffffffffffe0000001,1,3'd0,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h00000000001fffffff,1,3'd1,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h000000000020000000,1,3'd2,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h000000000020000001,1,3'd3,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h00000000005fffffff,1,3'd4,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h000000000060000000,1,3'd5,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h000000000060000001,1,3'd6,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h00000000009fffffff,1,3'd7,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h0000000000a0000000,1,3'd0,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h0000000000a0000001,1,3'd1,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h0000000000dfffffff,1,3'd2,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h0000000000e0000000,1,3'd3,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h0000000000e0000001,1,3'd4,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h001fffffffdffffffe,1,3'd5,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h001fffffffdfffffff,1,3'd6,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h001fffffffe0000000,1,3'd7,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h001fffffffe0000001,1,3'd0,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h001fffffffe0000002,1,3'd1,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffdfffffffdffffffe,1,3'd2,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffdfffffffdfffffff,1,3'd3,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffdfffffffe0000000,1,3'd4,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffdfffffffe0000001,1,3'd5,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffdfffffffe0000002,1,3'd6,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h7fffffffffdffffffe,1,3'd7,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h7fffffffffdfffffff,1,3'd0,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h7fffffffffe0000000,1,3'd1,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h7fffffffffe0000001,1,3'd2,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h7fffffffffe0000002,1,3'd3,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h800000000000000000,1,3'd4,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h800000000000000001,1,3'd5,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h7fffffffffffffffff,1,3'd6,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h7ffffffffffffffffe,1,3'd7,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h000000000000000000,1,3'd0,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h000000000000000001,1,3'd1,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffffffffffffffffff,1,3'd2,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h001fffffffc0000000,1,3'd3,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffe000000000000000,1,3'd4,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h001fffffff9fffffff,1,3'd5,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h001fffffffa0000000,1,3'd6,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h001fffffffa0000001,1,3'd7,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h00200000001fffffff,1,3'd0,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h002000000020000000,1,3'd1,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h002000000020000001,1,3'd2,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h003fffffff9fffffff,1,3'd3,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h003fffffffa0000000,1,3'd4,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h003fffffffa0000001,1,3'd5,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h003fffffffdfffffff,1,3'd6,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h003fffffffe0000000,1,3'd7,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h003fffffffe0000001,1,3'd0,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h005fffffff9fffffff,1,3'd1,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h005fffffffa0000000,1,3'd2,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h005fffffffa0000001,1,3'd3,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h005fffffffdfffffff,1,3'd4,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h005fffffffe0000000,1,3'd5,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h005fffffffe0000001,1,3'd6,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h00600000001fffffff,1,3'd7,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h006000000020000000,1,3'd0,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h006000000020000001,1,3'd1,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h007fffffff9fffffff,1,3'd2,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h007fffffffa0000000,1,3'd3,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h007fffffffa0000001,1,3'd4,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h007fffffffdfffffff,1,3'd5,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h007fffffffe0000000,1,3'd6,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h007fffffffe0000001,1,3'd7,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h7fdfffffff9fffffff,1,3'd0,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h7fdfffffffa0000000,1,3'd1,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h7fdfffffffa0000001,1,3'd2,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h7fdfffffffdfffffff,1,3'd3,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h7fdfffffffe0000000,1,3'd4,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h7fdfffffffe0000001,1,3'd5,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h7fe00000001fffffff,1,3'd6,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h7fe000000020000000,1,3'd7,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h7fe000000020000001,1,3'd0,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h7fffffffff9fffffff,1,3'd1,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h7fffffffffa0000000,1,3'd2,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h7fffffffffa0000001,1,3'd3,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h801fffffff9fffffff,1,3'd4,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h801fffffffa0000000,1,3'd5,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h801fffffffa0000001,1,3'd6,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h801fffffffdfffffff,1,3'd7,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h801fffffffe0000000,1,3'd0,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h801fffffffe0000001,1,3'd1,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h80200000001fffffff,1,3'd2,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h802000000020000000,1,3'd3,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h802000000020000001,1,3'd4,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h803fffffff9fffffff,1,3'd5,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h803fffffffa0000000,1,3'd6,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h803fffffffa0000001,1,3'd7,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h803fffffffdfffffff,1,3'd0,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h803fffffffe0000000,1,3'd1,1);literal_vectors=literal_vectors+1;
        drive_sample(72'h803fffffffe0000001,1,3'd2,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hff9fffffff9fffffff,1,3'd3,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hff9fffffffa0000000,1,3'd4,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hff9fffffffa0000001,1,3'd5,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hff9fffffffdfffffff,1,3'd6,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hff9fffffffe0000000,1,3'd7,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hff9fffffffe0000001,1,3'd0,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffa00000001fffffff,1,3'd1,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffa000000020000000,1,3'd2,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffa000000020000001,1,3'd3,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffbfffffff9fffffff,1,3'd4,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffbfffffffa0000000,1,3'd5,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffbfffffffa0000001,1,3'd6,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffbfffffffdfffffff,1,3'd7,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffbfffffffe0000000,1,3'd0,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffbfffffffe0000001,1,3'd1,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffdfffffff9fffffff,1,3'd2,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffdfffffffa0000000,1,3'd3,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffdfffffffa0000001,1,3'd4,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffe00000001fffffff,1,3'd5,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffe000000020000000,1,3'd6,1);literal_vectors=literal_vectors+1;
        drive_sample(72'hffe000000020000001,1,3'd7,1);literal_vectors=literal_vectors+1;
        low_class[0]=32'h00000000;low_class[1]=32'h7ffffffe;low_class[2]=32'h7fffffff;
        low_class[3]=32'h80000000;low_class[4]=32'hfffffffe;low_class[5]=32'hffffffff;
        fraction_class[0]=30'd536870911;fraction_class[1]=30'd536870912;fraction_class[2]=30'd536870913;
        for(h=0;h<1024;h=h+1)for(l=0;l<6;l=l+1)for(f=0;f<3;f=f+1)begin
            value={h[9:0],low_class[l],fraction_class[f]};
            drive_sample(value,1,(h+l+f)&7,1);exhaustive_vectors=exhaustive_vectors+1;
        end
        $display("[TB_MONITOR] all1024 high10 combinations completed");
        for(i=0;i<2048;i=i+1)begin
            rng=next_random(rng);rand_a=rng;rng=next_random(rng);rand_b=rng;
            rng=next_random(rng);rand_c=rng;value={rand_a[7:0],rand_b,rand_c};
            drive_sample(value,(i&3)!=0,i[2:0],1);random_vectors=random_vectors+1;
        end
        control(72'sh7fffffffffffffffff,1,7,0);
        control(0,0,0,1);
        for(i=0;i<8;i=i+1)control((72'sd31-i)<<30,1,i[2:0],1);
        if(group_seen_mask!==8'hff || literal_vectors!=120 || exhaustive_vectors!=18432 || random_vectors!=2048 || reset_cycles<3 || inhibit_cycles<3 || wrap_cases<3)
            $fatal(1,"[TB_ERROR] required coverage incomplete");
        $display("[TB_INFO] FIR_ROUND_SAT_PASS coeff_sets=2 groups=8 literal_vectors=%0d exhaustive_vectors=%0d random_vectors=%0d control_vectors=%0d vectors=%0d checks=%0d cone_checks=%0d writebacks=%0d held_group_checks=%0d clip_checks=%0d valid_checks=%0d reset_cycles=%0d inhibit_cycles=%0d positive_clip_cases=%0d negative_clip_cases=%0d inrange_cases=%0d half_tie_cases=%0d wrap_cases=%0d group_seen_mask=%02h",literal_vectors,exhaustive_vectors,random_vectors,control_vectors,vectors,checks,cone_checks,writebacks,held_group_checks,clip_checks,valid_checks,reset_cycles,inhibit_cycles,positive_clip_cases,negative_clip_cases,inrange_cases,half_tie_cases,wrap_cases,group_seen_mask);
        $display("[TB_INFO] Simulation Finished!");$finish;
    end
    initial begin #1000000;$fatal(1,"[TB_ERROR] watchdog");end
endmodule
