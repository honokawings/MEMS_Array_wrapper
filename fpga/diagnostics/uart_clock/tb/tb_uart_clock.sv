`timescale 1ns/1fs
module tb_uart_clock;
    reg ref27=0,ref125=0,grs_n=0,rx=1;
    wire tx;
    wire [3:0] mic_clk;
    wire phy_reset_n;
    always #(500.0/27.0) ref27=~ref27;
    always #4 ref125=~ref125;
    GTP_GRS GRS_INST(.GRS_N(grs_n));
    localparam integer DIV=4;
    localparam real BIT_NS=DIV*1000.0/27.0;
    uart_clock_diag #(.UART_DIV(DIV),.WINDOW_CYCLES(675),.PRESCALE_BITS(4),
        .REPORT_CYCLES(3000),.MS_CYCLES(270),.RESET_CYCLES(7000),.MODE_KEY_CYCLES(1000),
        .KEY_DEBOUNCE_CYCLES(16),.AUDIO_HEARTBEAT_CYCLES(64)) dut(
        .sys_clk_27(ref27),.sys_clk_125_p(ref125),.sys_clk_125_n(~ref125),
        .uart_rx(rx),.uart_tx(tx),.mic_clk(mic_clk),.phy_reset_n(phy_reset_n));
    integer checks=0,frames=0,old_frames;
    integer seqn,msn,locks,resets,freq,d0,d1,d2,d3,seen,fault,live,ctrl,rst,cmd,cmds,errs;
    integer previous_seq=-1,previous_ms=-1,parsed;
    reg [7:0] byte_rx;
    integer j;
    string line="";
    task check(input bit ok,input string message);
        begin checks=checks+1;if(!ok)$fatal(1,"[TB_ERROR] %s at %t",message,$time);end
    endtask
    initial begin
        wait(grs_n);wait(dut.observer_rst_n);
        forever begin
            @(negedge tx);#(BIT_NS*1.5);
            for(j=0;j<8;j=j+1)begin byte_rx[j]=tx;#(BIT_NS);end
            check(tx===1,"UART TX stop bit");
            line={line,byte_rx};
            if(byte_rx==10)begin
                if(line.len()!=159)$display("[TB_MONITOR] length=%0d raw=%s",line.len(),line);
                check(line.len()==159,"UART record exact length");
                parsed=$sscanf(line,"CLK2 pfd=31.25 seq=%h ms=%h lock=%b rst=%b freq=%b delta=%h,%h,%h,%h seen=%h fault=%h now=%h ctrl=%h reset=%b cmd=%h cmds=%h rxerr=%h",
                    seqn,msn,locks,resets,freq,d0,d1,d2,d3,seen,fault,live,ctrl,rst,cmd,cmds,errs);
                check(parsed==17,"all UART fields parse");
                check(seqn==previous_seq+1,"UART sequence monotonic");
                check(msn>=previous_ms,"observer uptime survives PLL reset");
                previous_seq=seqn;previous_ms=msn;frames=frames+1;
                $display("[TB_MONITOR] %s",line);$fflush();line="";
            end
        end
    end
    task send(input [7:0] value);
        integer b;
        begin
            @(negedge ref27);rx=0;repeat(DIV)@(negedge ref27);
            for(b=0;b<8;b=b+1)begin rx=value[b];repeat(DIV)@(negedge ref27);end
            rx=1;repeat(DIV)@(negedge ref27);
        end
    endtask
    initial begin
        #200;grs_n=1;
        wait(frames>=3);
        check(locks==7 && resets==7 && freq==15 && live==0 && fault==0,"healthy corrected PLLs reported through UART");
        check(d0>=193 && d0<=198 && d1>=148 && d1<=152,"125/96 source counts in accelerated window");
        check(d2>=190 && d2<=194 && d3>=193 && d3<=198,"audio/eth source counts in accelerated window");
        // The command receipt snapshot precedes the audio-domain debounce;
        // wait for its state to propagate back into a later coherent record.
        send("t");wait(cmds==1 && (ctrl&2)==2);check((ctrl&2)==2,"UART t enables original controller mode");
        send("t");wait(cmds==2 && (ctrl&2)==0);check((ctrl&2)==0,"UART t disables original controller mode");
        send("r");wait(cmds==3 && rst==1);
        check(resets==0,"UART reset actually holds global/local reset");
        wait(cmds==3 && rst==0 && freq==15 && resets==7);
        check(fault==0 && live==0,"UART reset/relock does not create false history");
        old_frames=frames;
        force dut.clocks.lock_eth=1'b0;
        wait(frames>=old_frames+2);
        check(locks==6 && resets==0 && freq==14,"UART describes missing eth lock and gated divided clock");
        check(fault==9 && live==9,"startup/current failure visible independently of history");
        check(d0>0 && d1>0 && d2>0 && d3==0,"raw clock deltas isolate stopped eth clock");
        release dut.clocks.lock_eth;
        wait(locks==7 && freq==15 && resets==7);
        check(fault==9 && live==0,"recovered UART report keeps prior fault");
        send("c");wait(cmds==4 && fault==0);check(live==0,"UART c clears history");
        old_frames=frames;send("s");wait(cmds==5 && frames>old_frames);
        check(cmd==8'h73 && errs==0,"UART status command acknowledged");
        check(mic_clk==0 && phy_reset_n==0,"microphones and PHY inactive");
        $display("[TB_INFO] Simulation Finished! checks=%0d frames=%0d",checks,frames);$finish;
    end
    initial begin #20000000;$fatal(1,"[TB_ERROR] UART clock test timeout");end
endmodule
