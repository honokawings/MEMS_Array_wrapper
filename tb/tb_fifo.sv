`timescale 1ns/1ps
module tb_fifo;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,valid_i=0,pcm_ready=0;
    reg [95:0] frame_i=0;
    reg [63:0] frame_id_i=0;
    wire signed [23:0] pcm_data;
    wire [6:0] pcm_channel;
    wire [63:0] pcm_frame_id;
    wire pcm_valid,pcm_first,pcm_last,overflow_o;
    wire [31:0] dropped_frames_o;
    pcm_frame_fifo #(.CHANNELS(4),.DEPTH(2)) dut(.*);
    integer accepted[0:63];
    integer head=0,tail=0,ch=0,dropped=0,seen=0,j;
    reg stalled=0;
    reg [97:0] held;
    function automatic [95:0] payload(input integer id);
        integer c;
        begin for(c=0;c<4;c=c+1) payload[c*24 +: 24]=id*100+c;end
    endfunction
    always @(posedge clk) begin
        if(!rst_n) begin head=0;tail=0;ch=0;dropped=0;stalled=0;seen=0;end
        else begin
            if(stalled && held!=={pcm_valid,pcm_data,pcm_channel,pcm_frame_id,pcm_first,pcm_last})
                $fatal(1,"[TB_ERROR] FIFO stall stability");
            stalled=pcm_valid&&!pcm_ready;
            held={pcm_valid,pcm_data,pcm_channel,pcm_frame_id,pcm_first,pcm_last};
            if(pcm_valid && pcm_ready) begin
                if(head==tail || pcm_frame_id!==accepted[head] || pcm_channel!==ch ||
                   pcm_data!==accepted[head]*100+ch || pcm_first!==(ch==0) || pcm_last!==(ch==3))
                    $fatal(1,"[TB_ERROR] FIFO ordering/data");
                seen=seen+1;
                if(ch==3) begin ch=0;head=head+1;end else ch=ch+1;
            end
            if(valid_i) begin
                if(tail-head<2) begin accepted[tail]=frame_id_i;tail=tail+1;end
                else dropped=dropped+1;
            end
        end
    end
    task automatic push(input integer id);
        begin
            @(negedge clk);valid_i=1;frame_i=payload(id);frame_id_i=id;
            @(negedge clk);valid_i=0;
        end
    endtask
    initial begin
        repeat(3) @(negedge clk);rst_n=1;
        push(0);push(1);push(2);push(3);push(4);
        if(!overflow_o || dropped_frames_o!=3) $fatal(1,"[TB_ERROR] Whole-frame drop count");
        @(negedge clk);pcm_ready=1;
        wait(pcm_valid && pcm_last);
        @(negedge clk);valid_i=1;frame_i=payload(5);frame_id_i=5;
        @(negedge clk);valid_i=0;
        wait(!pcm_valid);@(negedge clk);
        if(head!=tail || seen!=12 || dropped_frames_o!=dropped)
            $fatal(1,"[TB_ERROR] Full simultaneous dequeue/enqueue");
        for(j=6;j<20;j=j+1) push(j);
        wait(!pcm_valid);@(negedge clk);
        if(head!=tail || dropped_frames_o!=dropped) $fatal(1,"[TB_ERROR] FIFO burst accounting");
        pcm_ready=0;push(30);
        rst_n=0;repeat(2) @(negedge clk);rst_n=1;
        if(pcm_valid || overflow_o || dropped_frames_o) $fatal(1,"[TB_ERROR] FIFO reset");
        $display("[TB_DATA] FIFO full, atomic drop, simultaneous pop/push, burst, stall, reset passed");
        $display("[TB_INFO] Simulation Finished!");$finish;
    end
    initial begin #100_000;$fatal(1,"[TB_ERROR] FIFO watchdog");end
endmodule
