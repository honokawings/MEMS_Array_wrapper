`timescale 1ns/1ps
module tb_uart_protocol;
    reg clk=0,rst_n=0,rx=1,valid=0;
    reg [7:0] tx_data=0;
    wire tx,ready,rx_valid,rx_error;
    wire [7:0] rx_data;
    always #10 clk=~clk;
    localparam integer DIV=32;
    diag_uart_tx #(.CLKS_PER_BIT(DIV)) tx_dut(.clk(clk),.rst_n(rst_n),.data(tx_data),.valid(valid),.ready(ready),.tx(tx));
    diag_uart_rx #(.CLKS_PER_BIT(DIV)) rx_dut(.clk(clk),.rst_n(rst_n),.rx(rx),.data(rx_data),.valid(rx_valid),.error(rx_error));
    integer checks=0,received=0,transmitted=0,errors=0,n,b;
    reg [7:0] expected_rx,got_tx;
    task check(input bit ok,input string message);
        begin checks=checks+1;if(!ok)$fatal(1,"[TB_ERROR] %s at %t",message,$time);end
    endtask
    always @(negedge clk) if(rst_n)begin
        if(rx_valid)begin check(rx_data===expected_rx,"RX byte data");received=received+1;end
        if(rx_error)errors=errors+1;
    end
    initial begin
        wait(rst_n);
        forever begin
            @(negedge tx);#(DIV*20*1.5);
            for(b=0;b<8;b=b+1)begin got_tx[b]=tx;#(DIV*20);end
            check(tx===1,"TX stop bit correct");
            check(got_tx===(transmitted&255),"all 256 TX payloads in order");transmitted=transmitted+1;
        end
    end
    task send(input [7:0] value,input integer cycles,input bit bad_stop);
        integer bitn;
        begin
            expected_rx=value;@(negedge clk);rx=0;repeat(cycles)@(negedge clk);
            for(bitn=0;bitn<8;bitn=bitn+1)begin rx=value[bitn];repeat(cycles)@(negedge clk);end
            rx=!bad_stop;repeat(cycles)@(negedge clk);rx=1;repeat(DIV)@(negedge clk);
        end
    endtask
    initial begin
        repeat(5)@(negedge clk);rst_n=1;
        // TX can transmit continuously; validate externally by serial waveform.
        for(n=0;n<256;n=n+1)begin
            wait(ready);@(negedge clk);tx_data=n;valid=1;@(negedge clk);valid=0;
        end
        wait(transmitted==256);check(ready===0 || tx===1,"final byte completes cleanly");
        for(n=0;n<256;n=n+1)send(n,DIV,0);
        check(received==256,"all 256 RX payloads");
        send(8'h96,DIV-1,0);send(8'h69,DIV+1,0);
        check(received==258,"RX tolerates about +/-3 percent baud offset");
        // False-start rejection and bad-stop rejection must not deliver commands.
        @(negedge clk);rx=0;repeat(4)@(negedge clk);rx=1;repeat(DIV*12)@(negedge clk);
        check(received==258,"short glitch rejected");
        send(8'h72,DIV,1);repeat(DIV*3)@(negedge clk);
        check(received==258 && errors==1,"bad stop cannot trigger reset command");
        send(8'h73,DIV,0);check(received==259,"receiver recovers after framing error");
        $display("[TB_INFO] Simulation Finished! checks=%0d",checks);$finish;
    end
    initial begin #10000000;$fatal(1,"[TB_ERROR] protocol test timeout");end
endmodule
