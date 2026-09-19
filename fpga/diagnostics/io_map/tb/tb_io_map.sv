`timescale 1ns/1ps
module tb_io_map;
    reg grs_n=0, clk=0;
    reg [4:0] key_n=5'b11111;
    wire [4:0] direct_led,walk_led;
    wire [3:0] direct_mic,walk_mic;
    wire direct_phy,walk_phy;
    GTP_GRS GRS_INST(.GRS_N(grs_n));
    io_map_direct direct_dut(.key_n(key_n),.led(direct_led),.mic_clk(direct_mic),.phy_reset_n(direct_phy));
    io_map_walk #(.STEP_CYCLES(4)) walk_dut(.sys_clk_27(clk),.key_n(key_n),.led(walk_led),
        .mic_clk(walk_mic),.phy_reset_n(walk_phy));
    integer checks=0, phase, cycle, mask;
    function automatic [4:0] expected_pattern(input integer phase_number);
        case(phase_number%10)
            0,2: expected_pattern=31;
            4: expected_pattern=1;
            5: expected_pattern=2;
            6: expected_pattern=4;
            7: expected_pattern=8;
            8: expected_pattern=16;
            default: expected_pattern=0;
        endcase
    endfunction
    task automatic check(input [4:0] exp_direct,exp_walk);
        begin
            checks=checks+1;
            if(direct_led!==exp_direct || walk_led!==exp_walk)
                $fatal(1,"[TB_ERROR] key=%b direct=%b/%b walk=%b/%b",key_n,direct_led,exp_direct,walk_led,exp_walk);
            if({direct_phy,walk_phy,direct_mic,walk_mic}!==10'b0)
                $fatal(1,"[TB_ERROR] PHY/microphone outputs not held low");
        end
    endtask
    task automatic tick;
        begin clk=0;#5;clk=1;#5;clk=0;#1;end
    endtask
    initial begin
        #20;check(0,31);grs_n=1;#5;
        // Two complete visible signatures; exact phase duration and wrap.
        for(phase=0;phase<20;phase=phase+1)
            for(cycle=0;cycle<4;cycle=cycle+1) begin
                check(0,expected_pattern(phase));tick();
            end
        check(0,31);
        $display("[TB_DATA] Two complete ALL/OFF/one-hot sequences and period PASS");
        // Exhaust all 32 key combinations with the oscillator stopped.
        for(mask=0;mask<32;mask=mask+1) begin
            key_n=~mask;#3;
            check(mask,mask==0 ? 31 : mask);
        end
        key_n=31;#3;check(0,31);
        $display("[TB_DATA] All 32 key combinations with clock stopped PASS");
        // KEY0 is a normal input. Holding it does not reset or stop the scan.
        key_n=30;#3;
        for(cycle=0;cycle<20;cycle=cycle+1) begin check(1,1);tick();end
        key_n=31;#3;check(0,2); // Phase 5, LED1 after 20 more edges.
        $display("[TB_DATA] KEY0 override, continued counting and release PASS");
        // Reconfiguration global reset restores the pattern without any key.
        grs_n=0;#5;check(0,31);grs_n=1;#5;
        $display("[TB_INFO] Simulation Finished! checks=%0d",checks);
        $finish;
    end
    initial begin #100000;$fatal(1,"[TB_ERROR] Timeout");end
endmodule
