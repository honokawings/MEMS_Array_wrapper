`timescale 1ns/1ps
module tb_selftest_faults;
    reg clk=0;always #4 clk=~clk;
    reg rst_n=0,key_n=1,local_pass=0,local_fail=0,link_up=0,phy_fault=0,tx_pass=0,tx_fault=0;
    wire mode;wire [4:0] led;
    board_selftest_control #(.DEBOUNCE_CYCLES(4),.HEARTBEAT_CYCLES(8),.WAIT_CYCLES(100)) control(
        .clk(clk),.rst_n(rst_n),.key_n(key_n),.local_pass(local_pass),.local_fail(local_fail),
        .link_up(link_up),.phy_fault(phy_fault),.tx_pass(tx_pass),.tx_fault(tx_fault),.selftest_mode(mode),.led(led));
    reg enable=0,valid=0,first=1,last=0,error=0;
    reg [23:0] data=0;reg [6:0] channel=0;reg [63:0] frame=96;
    wire passed,failed;wire [31:0] frames;
    pcm_selftest_checker #(.PASS_FRAMES(16),.TIMEOUT_CYCLES(8)) checker_inst(
        .clk(clk),.rst_n(rst_n),.enable(enable),.pcm_data(data),.pcm_channel(channel),
        .pcm_frame_id(frame),.pcm_valid(valid),.pcm_ready(1'b1),.pcm_first(first),.pcm_last(last),
        .pipeline_error(error),.passed(passed),.failed(failed),.checked_frames(frames),.first_bad_frame(),.first_bad_channel());
    task automatic check(input bit ok,input string msg);if(!ok)$fatal(1,"[TB_ERROR] %s",msg);endtask
    task automatic press;
        begin key_n=0;repeat(12)@(negedge clk);key_n=1;repeat(12)@(negedge clk);end
    endtask
    initial begin
        repeat(4)@(negedge clk);rst_n=1;repeat(4)@(negedge clk);
        key_n=0;repeat(50)@(negedge clk);check(mode,"long hold toggled twice");key_n=1;repeat(10)@(negedge clk);
        repeat(60)@(negedge clk);check(led[4],"waiting for absent link/data never timed out");
        local_pass=1;tx_pass=1;link_up=1;repeat(8)@(negedge clk);check(led[4],"timeout not sticky");
        press();check(!mode && !led[4],"exit did not reset timeout");press();check(mode && led[2] && led[3] && !led[4],"normal status encoding");
        phy_fault=1;repeat(8)@(negedge clk);check(led[4],"PHY fault not shown");phy_fault=0;
        press();press();tx_fault=1;repeat(8)@(negedge clk);check(led[4],"TX fault not shown");
        enable=1;repeat(12)@(negedge clk);check(failed && !passed,"missing PCM did not time out");
        enable=0;@(negedge clk);enable=1;error=1;@(negedge clk);check(failed,"pipeline fault not detected");
        error=0;enable=0;@(negedge clk);enable=1;valid=1;data=checker_inst.expected_rom[1];channel=1;
        repeat(2)@(negedge clk);valid=0;check(failed,"channel sequence error not detected");
        enable=0;@(negedge clk);enable=1;valid=1;channel=0;data=checker_inst.expected_rom[0];frame=112;
        repeat(2)@(negedge clk);valid=0;check(failed,"frame sequence error not detected");
        rst_n=0;repeat(4)@(negedge clk);check(!failed && !mode && led==0,"reset did not recover faults");
        $display("[TB_DATA] Debounce/hold, no-link timeout, sticky PHY/TX status, missing PCM, channel/frame errors and reset PASS");
        $display("[TB_INFO] Simulation Finished!");$finish;
    end
endmodule
