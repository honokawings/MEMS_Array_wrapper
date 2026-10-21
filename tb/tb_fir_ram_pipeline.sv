`timescale 1ns/1ps
// Reference transactions come from externally accepted input vectors.  RAM
// addresses, read samples and full convolution are checked independently of
// the DUT's delayed write/index state machines.
module fir_ram_case #(
    parameter integer ID=0,
    parameter integer CHANNELS=128,
    parameter integer LANES=16,
    parameter integer TAPS=63,
    parameter integer DEPTH=128,
    parameter integer DECIMATION=4,
    parameter integer COEFF_SET=1,
    parameter integer INPUT_INTERVAL=320,
    // Independent constants for the new production-lane cases; old cases
    // retain the established parameterized latency oracle.
    parameter integer EXPECTED_LATENCY=0
) (input wire clk,output reg done=0);
    localparam integer GROUPS=CHANNELS/LANES;
    localparam integer INPUTS=2*DEPTH+8;
    localparam integer MAX_INPUTS=INPUTS+32;
    localparam integer DRAIN=GROUPS*(TAPS+4)+GROUPS+8;
    reg rst_n=0,valid_i=0,expect_reject=0,allow_overrun=0;
    reg [CHANNELS*32-1:0] data_i=0;
    wire [CHANNELS*32-1:0] data_o;
    wire valid_o,overrun_o,clip_o;
    fir_decimator #(.CHANNELS(CHANNELS),.LANES(LANES),.TAPS(TAPS),
        .DEPTH(DEPTH),.DECIMATION(DECIMATION),.COEFF_SET(COEFF_SET)) dut(.*);
    reg signed [31:0] reference_inputs[0:MAX_INPUTS*CHANNELS-1];
    reg signed [31:0] coefficients[0:TAPS-1];
    integer input_cycles[0:MAX_INPUTS-1];
    integer epoch=0,drive_sequence=0;
    integer cycle=0,accepted=0,commits=0,reads=0,outputs=0;
    integer checks=0,total_writes=0,total_reads=0,total_outputs=0;
    integer wraps=0,reset_cases=0,concurrent_rw=0,short_capture=0;
    integer writing_faults=0,busy_faults=0,input_changes=0;
    reg write_check=0,read_check=0;
    integer observed_write_address,observed_read_address;
    integer write_sequence,write_group_ref;
    integer read_base_sequence,read_group_ref,read_tap_ref;
    integer expected_output_base,channel,tap;
    reg signed [63:0] ref_product;
    reg signed [71:0] ref_sum,ref_rounded;
    reg signed [31:0] expected_output;
    reg reference_clipped=0;

    function automatic signed [31:0] external_word(input integer run_id,input integer seq,input integer ch);
        reg signed [31:0] value;
        begin
            value=32'sd19+run_id*32'sd2097152+seq*32'sd4099+ch*32'sd257;
            external_word=((seq+ch)&1)?-value:value;
        end
    endfunction
    function automatic signed [31:0] history_reference(input integer seq,input integer ch);
        begin
            if(seq<0) history_reference=0;
            else if(seq>=accepted) $fatal(1,"[TB_ERROR] case=%0d reference read future seq=%0d accepted=%0d",ID,seq,accepted);
            else history_reference=reference_inputs[seq*CHANNELS+ch];
        end
    endfunction

    // Observe physical RAM-port transactions before the edge.  Expected
    // sequence/group/tap are ordinal positions in the external stream, not
    // copied DUT write_pointer/issue_count/compute_group values.
    always @(posedge clk) begin
        write_check=0;read_check=0;
        if(!rst_n) begin
            cycle=0;accepted=0;commits=0;reads=0;outputs=0;reference_clipped=0;
        end else if(!done) begin
            cycle=cycle+1;
            if(valid_i) begin
                if(expect_reject) begin
                    if(!dut.writing) $fatal(1,"[TB_ERROR] case=%0d intended writing fault not in write interval",ID);
                    checks=checks+1;
                end else begin
                    if(dut.writing || accepted>=MAX_INPUTS) $fatal(1,"[TB_ERROR] case=%0d legal input unexpectedly blocked",ID);
                    input_cycles[accepted]=cycle;
                    for(channel=0;channel<CHANNELS;channel=channel+1)
                        reference_inputs[accepted*CHANNELS+channel]=$signed(data_i[channel*32 +: 32]);
                    accepted=accepted+1;
                    if(dut.write_commit_valid && dut.write_commit_last) short_capture=short_capture+1;
                end
            end
            if(dut.write_commit_valid) begin
                write_check=1;
                write_sequence=commits/GROUPS;write_group_ref=commits%GROUPS;
                observed_write_address=dut.write_commit_address;
                if(write_sequence>=accepted || observed_write_address!=write_group_ref*DEPTH+(write_sequence%DEPTH))
                    $fatal(1,"[TB_ERROR] case=%0d RAM write address got=%0d external_seq=%0d group=%0d",ID,observed_write_address,write_sequence,write_group_ref);
                if(dut.write_commit_last!==(write_group_ref==GROUPS-1) ||
                    cycle!=input_cycles[write_sequence]+write_group_ref+2)
                    $fatal(1,"[TB_ERROR] case=%0d RAM commit alignment seq=%0d group=%0d cycle=%0d",ID,write_sequence,write_group_ref,cycle);
                if(write_group_ref==GROUPS-1 && write_sequence>0 && write_sequence%DEPTH==0) wraps=wraps+1;
                commits=commits+1;total_writes=total_writes+LANES;checks=checks+2;
            end
            if(dut.issue) begin
                read_check=1;
                read_base_sequence=(reads/(GROUPS*TAPS)+1)*DECIMATION-1;
                read_group_ref=(reads/TAPS)%GROUPS;read_tap_ref=reads%TAPS;
                observed_read_address=dut.compute_group*DEPTH+dut.read_pointer;
                if(observed_read_address!=read_group_ref*DEPTH+((read_base_sequence-read_tap_ref)&(DEPTH-1)))
                    $fatal(1,"[TB_ERROR] case=%0d RAM read address got=%0d external_base=%0d group=%0d tap=%0d",ID,observed_read_address,read_base_sequence,read_group_ref,read_tap_ref);
                if(write_check) begin
                    concurrent_rw=concurrent_rw+1;
                    if(observed_read_address==observed_write_address)
                        $fatal(1,"[TB_ERROR] case=%0d RAM same-address read/write depends on primitive mode",ID);
                end
                reads=reads+1;total_reads=total_reads+LANES;checks=checks+1;
            end
            #1;
            if(overrun_o && !allow_overrun) $fatal(1,"[TB_ERROR] case=%0d unexpected overrun",ID);
            if(valid_o) begin
                expected_output_base=(outputs+1)*DECIMATION-1;
                if(cycle!=input_cycles[expected_output_base]+
                        ((EXPECTED_LATENCY>0)?EXPECTED_LATENCY:GROUPS+2+GROUPS*(TAPS+4)))
                    $fatal(1,"[TB_ERROR] case=%0d output latency got=%0d base=%0d input_cycle=%0d",ID,cycle,expected_output_base,input_cycles[expected_output_base]);
                for(channel=0;channel<CHANNELS;channel=channel+1) begin
                    ref_sum=0;
                    for(tap=0;tap<TAPS;tap=tap+1) begin
                        ref_product=$signed(history_reference(expected_output_base-tap,channel))*$signed(coefficients[tap]);
                        ref_sum=ref_sum+{{8{ref_product[63]}},ref_product};
                    end
                    // Independent signed-magnitude nearest rounding.
                    if(ref_sum<0) ref_rounded=-(((-ref_sum)+(72'sd1<<29))>>>30);
                    else ref_rounded=(ref_sum+(72'sd1<<29))>>>30;
                    if(ref_rounded>72'sd2147483647) begin expected_output=32'h7fffffff;reference_clipped=1;end
                    else if(ref_rounded < -72'sd2147483648) begin expected_output=32'h80000000;reference_clipped=1;end
                    else expected_output=ref_rounded[31:0];
                    if(data_o[channel*32 +: 32]!==expected_output)
                        $fatal(1,"[TB_ERROR] case=%0d full convolution output=%0d channel=%0d got=%0d expected=%0d",ID,outputs,channel,$signed(data_o[channel*32 +: 32]),expected_output);
                    checks=checks+1;
                end
                outputs=outputs+1;total_outputs=total_outputs+CHANNELS;checks=checks+1;
                if(clip_o!==reference_clipped) $fatal(1,"[TB_ERROR] case=%0d sticky clip mismatch",ID);
            end
        end
    end

    genvar lane_number;
    generate for(lane_number=0;lane_number<LANES;lane_number=lane_number+1) begin: ram_check
        reg wr,rd;
        integer address;
        reg signed [31:0] expected_write,expected_read;
        always @(posedge clk) begin
            // The common monitor prepares ordinal references in the active
            // region; #0 samples the old port data before nonblocking updates.
            #0;
            wr=write_check;rd=read_check;address=observed_write_address;
            if(wr) begin
                expected_write=history_reference(write_sequence,write_group_ref*LANES+lane_number);
                if(dut.lane[lane_number].write_data!==expected_write)
                    $fatal(1,"[TB_ERROR] case=%0d lane=%0d write data lost input snapshot",ID,lane_number);
                checks=checks+1;
            end
            if(rd) expected_read=history_reference(read_base_sequence-read_tap_ref,read_group_ref*LANES+lane_number);
            #1;
            if(wr) begin
                if(dut.lane[lane_number].history[address]!==expected_write)
                    $fatal(1,"[TB_ERROR] case=%0d lane=%0d actual RAM write mismatch addr=%0d",ID,lane_number,address);
                checks=checks+1;
            end
            if(rd) begin
                if(dut.lane[lane_number].read_sample!==expected_read)
                    $fatal(1,"[TB_ERROR] case=%0d lane=%0d actual RAM read mismatch",ID,lane_number);
                checks=checks+1;
            end
        end
    end endgenerate

    task automatic set_input;
        integer ch;
        begin
            for(ch=0;ch<CHANNELS;ch=ch+1) data_i[ch*32 +: 32]=external_word(epoch,drive_sequence,ch);
            drive_sequence=drive_sequence+1;valid_i=1;expect_reject=0;
        end
    endtask
    task automatic pulse_input;
        begin
            @(negedge clk);set_input();
            @(negedge clk);valid_i=0;data_i=~data_i;input_changes=input_changes+1;
        end
    endtask
    task automatic send_input(input integer interval);
        begin
            pulse_input();
            repeat(interval-2) begin @(negedge clk);data_i={data_i[CHANNELS*32-2:0],~data_i[CHANNELS*32-1]};input_changes=input_changes+1;end
        end
    endtask
    task automatic reset_device;
        begin
            @(negedge clk);rst_n=0;valid_i=0;expect_reject=0;allow_overrun=0;
            epoch=epoch+1;drive_sequence=0;
            repeat(4) @(negedge clk);
            rst_n=1;
        end
    endtask
    task automatic check_drained(input integer inputs_expected,input integer outputs_expected,input reg fault_expected);
        begin
            repeat(DRAIN) @(negedge clk);
            if(accepted!=inputs_expected || commits!=inputs_expected*GROUPS ||
                reads!=outputs_expected*GROUPS*TAPS || outputs!=outputs_expected || overrun_o!==fault_expected)
                $fatal(1,"[TB_ERROR] case=%0d incomplete transactions in=%0d wr=%0d rd=%0d out=%0d fault=%b",ID,accepted,commits,reads,outputs,overrun_o);
            checks=checks+5;
        end
    endtask
    task automatic restart_and_check;
        integer n;
        begin
            reset_device();
            for(n=0;n<DECIMATION;n=n+1) send_input(INPUT_INTERVAL);
            check_drained(DECIMATION,1,0);
        end
    endtask
    task automatic interrupt_phase(input integer phase);
        integer n;
        begin
            reset_device();
            for(n=0;n<DECIMATION-1;n=n+1) send_input(INPUT_INTERVAL);
            pulse_input();
            if(phase==0) wait(dut.write_commit_valid);
            else if(phase==1) wait(dut.write_commit_valid && dut.write_commit_last);
            else begin
                wait(dut.busy && dut.issue);
                if(phase==3) begin @(posedge clk);#1;end
            end
            restart_and_check();reset_cases=reset_cases+1;
        end
    endtask
    integer n,phase;
    initial begin
        if(COEFF_SET==1) $readmemh("../../lib/coeff/fir1_q30.hex",coefficients);
        else $readmemh("../../lib/coeff/fir2_q30.hex",coefficients);
        reset_device();
        for(n=0;n<INPUTS;n=n+1) send_input(INPUT_INTERVAL);
        check_drained(INPUTS,INPUTS/DECIMATION,0);
        if(wraps<2) $fatal(1,"[TB_ERROR] case=%0d insufficient physical RAM wraps",ID);
        for(phase=0;phase<4;phase=phase+1) interrupt_phase(phase);

        // Replace input_hold exactly when the preceding final write commits.
        reset_device();pulse_input();
        wait(dut.write_commit_valid && dut.write_commit_last);
        @(negedge clk);set_input();
        @(negedge clk);valid_i=0;data_i=~data_i;input_changes=input_changes+1;
        repeat(INPUT_INTERVAL) @(negedge clk);
        for(n=2;n<DECIMATION;n=n+1) send_input(INPUT_INTERVAL);
        check_drained(DECIMATION,1,0);
        if(short_capture<1) $fatal(1,"[TB_ERROR] case=%0d final commit/new input coincidence missing",ID);

        // A changed input during writing is rejected, without corrupting RAM.
        reset_device();allow_overrun=1;pulse_input();
        valid_i=1;expect_reject=1;data_i='1;
        @(negedge clk);valid_i=0;expect_reject=0;
        repeat(INPUT_INTERVAL) @(negedge clk);
        for(n=1;n<DECIMATION;n=n+1) send_input(INPUT_INTERVAL);
        check_drained(DECIMATION,1,1);writing_faults=writing_faults+1;

        // Faster legal writes eventually request a second job while the
        // first is busy. Check the fault, then cancel and prove clean restart.
        reset_device();allow_overrun=1;
        for(n=0;n<DECIMATION-1;n=n+1) send_input(INPUT_INTERVAL);
        pulse_input();wait(dut.busy);
        for(n=0;n<DECIMATION;n=n+1) send_input(GROUPS+2);
        repeat(GROUPS+3) @(negedge clk);
        if(!overrun_o) $fatal(1,"[TB_ERROR] case=%0d busy scheduling fault not detected",ID);
        busy_faults=busy_faults+1;checks=checks+1;
        restart_and_check();
        if(concurrent_rw<1 || reset_cases!=4 || input_changes<INPUTS || writing_faults!=1 || busy_faults!=1)
            $fatal(1,"[TB_ERROR] case=%0d required RAM coverage missing",ID);
        $display("[TB_DATA] FIR_RAM case=%0d channels=%0d lanes=%0d groups=%0d taps=%0d depth=%0d decimation=%0d input_interval=%0d checks=%0d writes=%0d reads=%0d output_samples=%0d wraps=%0d concurrent_rw=%0d resets=%0d commit_capture=%0d writing_faults=%0d busy_faults=%0d input_changes=%0d",ID,CHANNELS,LANES,GROUPS,TAPS,DEPTH,DECIMATION,INPUT_INTERVAL,checks,total_writes,total_reads,total_outputs,wraps,concurrent_rw,reset_cases,short_capture,writing_faults,busy_faults,input_changes);
        done=1;rst_n=0;
    end
endmodule

module tb_fir_ram_pipeline;
    reg clk=0;
    always #4.069 clk=~clk;
    wire [5:0] done;
    fir_ram_case #(.ID(0)) production_fir1(.clk(clk),.done(done[0]));
    fir_ram_case #(.ID(1),.TAPS(127),.DEPTH(256),.DECIMATION(2),.COEFF_SET(2),.INPUT_INTERVAL(1280)) production_fir2(.clk(clk),.done(done[1]));
    fir_ram_case #(.ID(2),.CHANNELS(1),.LANES(1),.INPUT_INTERVAL(32)) single_group_fir1(.clk(clk),.done(done[2]));
    fir_ram_case #(.ID(3),.CHANNELS(1),.LANES(1),.TAPS(127),.DEPTH(256),.DECIMATION(2),.COEFF_SET(2),.INPUT_INTERVAL(72)) single_group_fir2(.clk(clk),.done(done[3]));
    // Production input cadence with half as many multiplier lanes.
    fir_ram_case #(.ID(4),.LANES(8),.EXPECTED_LATENCY(1090)) eight_lane_fir1(.clk(clk),.done(done[4]));
    fir_ram_case #(.ID(5),.LANES(8),.TAPS(127),.DEPTH(256),.DECIMATION(2),.COEFF_SET(2),.INPUT_INTERVAL(1280),.EXPECTED_LATENCY(2114)) eight_lane_fir2(.clk(clk),.done(done[5]));
    initial begin
        wait(&done);
        $display("[TB_INFO] FIR_RAM all six configurations passed; actual RAM, independent convolution, reset and faults");
        $display("[TB_INFO] Simulation Finished!");$finish;
    end
    initial begin #10000000;$fatal(1,"[TB_ERROR] FIR_RAM watchdog");end
endmodule
