`timescale 1ns/1ps
// KEY1 toggles mode once per debounced press. Status inputs from Ethernet are
// synchronized levels. No packet pulse crosses clock domains.
module board_selftest_control #(
    parameter integer DEBOUNCE_CYCLES=2457600,
    parameter integer HEARTBEAT_CYCLES=61440000,
    parameter integer WAIT_CYCLES=1228800000
) (
    input wire clk,rst_n,key_n,
    input wire local_pass,local_fail,link_up,phy_fault,tx_pass,tx_fault,
    output reg selftest_mode,
    output wire [4:0] led
);
    (* syn_preserve=1 *) reg key_meta,key_sync;
    reg stable_key,heartbeat;
    reg [31:0] debounce_count,heartbeat_count,wait_count;
    (* syn_preserve=1 *) reg [3:0] status_meta,status_sync;
    reg session_fault;
    wire press=(key_sync!=stable_key) && debounce_count==DEBOUNCE_CYCLES-1 && !key_sync;
    assign led={selftest_mode && (session_fault || local_fail || status_sync[3] || status_sync[1]),
                selftest_mode ? status_sync[2] : status_sync[0],
                selftest_mode && local_pass,selftest_mode,heartbeat};
    always @(posedge clk) begin
        if(!rst_n) begin
            key_meta<=1;key_sync<=1;stable_key<=1;debounce_count<=0;
            selftest_mode<=0;heartbeat_count<=0;heartbeat<=0;
            status_meta<=0;status_sync<=0;wait_count<=0;session_fault<=0;
        end else begin
            key_meta<=key_n;key_sync<=key_meta;
            status_meta<={tx_fault,tx_pass,phy_fault,link_up};status_sync<=status_meta;
            if(key_sync==stable_key) debounce_count<=0;
            else if(debounce_count==DEBOUNCE_CYCLES-1) begin
                stable_key<=key_sync;debounce_count<=0;
                if(!key_sync) selftest_mode<=!selftest_mode;
            end else debounce_count<=debounce_count+1'b1;
            if(heartbeat_count==HEARTBEAT_CYCLES-1) begin heartbeat_count<=0;heartbeat<=!heartbeat;end
            else heartbeat_count<=heartbeat_count+1'b1;
            if(!selftest_mode || press) begin wait_count<=0;session_fault<=0;end
            else if(!(local_pass && status_sync[2])) begin
                if(wait_count==WAIT_CYCLES-1) session_fault<=1;
                else wait_count<=wait_count+1'b1;
            end
            if(selftest_mode && (local_fail || status_sync[3] || status_sync[1])) session_fault<=1;
        end
    end
endmodule
