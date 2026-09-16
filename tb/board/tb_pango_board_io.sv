`timescale 1ns/1fs
module tb_pango_board_io;
    reg ref27 = 0, ref125 = 0, rst_n = 0;
    always #(500.0/27.0) ref27 = ~ref27;
    real ref125_high = 3.6;
    // Exercise the oscillator's two specified duty extremes at a fixed 8 ns
    // rising-edge period. The dedicated divide-by-two must remove this DCD.
    initial forever begin
        ref125 = 1'b1; #(ref125_high);
        ref125 = 1'b0; #(8.0-ref125_high);
    end
    wire audio_clk, eth_clk, locked;
    GTP_GRS GRS_INST (.GRS_N(rst_n));
    pango_board_clocks clocks (
        .ref_clk_27(ref27), .ref_clk_125_p(ref125), .ref_clk_125_n(~ref125),
        .rst_n(rst_n), .audio_clk(audio_clk), .eth_clk(eth_clk), .locked(locked));

    reg [7:0] tx_data = 0;
    reg tx_en = 0, tx_er = 0;
    wire [3:0] txd;
    wire txc, txctl, rxc, rxclk, rx_dv, rx_er;
    wire [7:0] rx_data;
    // The external PHY's configured 2 ns receive clock skew.
    assign #2 rxc = txc;
    pango_rgmii_io io (
        .tx_clk(eth_clk), .rst_n(rst_n), .tx_data(tx_data), .tx_en(tx_en), .tx_er(tx_er),
        .rgmii_rxc(rxc), .rgmii_rx_ctl(txctl), .rgmii_rxd(txd),
        .rx_clk(rxclk), .rx_data(rx_data), .rx_dv(rx_dv), .rx_er(rx_er),
        .rgmii_txc(txc), .rgmii_tx_ctl(txctl), .rgmii_txd(txd));
    integer rx_count=0, tx_count=0, batches=0;
    reg monitor_enable=0;
    reg [7:0] held_data;
    reg held_en, held_er;
    reg [7:0] previous_data=0;
    reg previous_en=0, previous_er=0;
    realtime start_time, measured;

    function automatic [7:0] pattern(input integer index);
        pattern = (index*73 + 41) & 255;
    endfunction
    always @(posedge eth_clk) begin
        // GTP_ODDR_E1 SAME_EDGE launches the byte one complete clock after capture.
        held_data=previous_data; held_en=previous_en; held_er=previous_er;
        previous_data=tx_data; previous_en=tx_en; previous_er=tx_er;
        #0.1;
        if (monitor_enable && (txd !== held_data[3:0] || txctl !== held_en))
            $fatal(1,"[TB_ERROR] ODDR rising nibble/control mismatch");
    end
    always @(negedge eth_clk) begin
        #0.1;
        if (monitor_enable && (txd !== held_data[7:4] || txctl !== (held_en^held_er)))
            $fatal(1,"[TB_ERROR] ODDR falling nibble/control mismatch");
    end
    always @(posedge rxclk) begin
        #0.2;
        if (rst_n && rx_dv) begin
            if (rx_data !== pattern(rx_count % 256) || rx_er !== ((rx_count%4)==3))
                $fatal(1,"[TB_ERROR] IDDR byte/control mismatch index=%0d got=%02x er=%b",rx_count,rx_data,rx_er);
            rx_count=rx_count+1;
        end
    end
    task check_audio;
        begin
            wait(locked===1'b1);
            repeat(30) @(posedge audio_clk);
            start_time=$realtime;
            repeat(256) @(posedge audio_clk);
            measured=($realtime-start_time)/256.0;
            if (measured < 8.1370 || measured > 8.1391)
                $fatal(1,"[TB_ERROR] 122.88 MHz period mismatch: %0.9f ns",measured);
            $display("[TB_MONITOR] audio period=%0.9f ns PLLs locked",measured);
        end
    endtask
    task check_eth_duty;
        realtime edge_time, interval;
        integer cycle;
        begin
            wait(locked===1'b1);
            repeat(20) @(posedge eth_clk);
            for (cycle=0; cycle<64; cycle=cycle+1) begin
                edge_time=$realtime;
                @(negedge eth_clk); interval=$realtime-edge_time;
                if (interval < 3.995 || interval > 4.005)
                    $fatal(1,"[TB_ERROR] shaped eth125 high time: %0.9f ns",interval);
                edge_time=$realtime;
                @(posedge eth_clk); interval=$realtime-edge_time;
                if (interval < 3.995 || interval > 4.005)
                    $fatal(1,"[TB_ERROR] shaped eth125 low time: %0.9f ns",interval);
            end
            $display("[TB_MONITOR] eth125 high/low=4 ns for oscillator duty=%0.1f%%",ref125_high*12.5);
        end
    endtask
    initial begin
        #200 rst_n=1;
        check_audio();
        check_eth_duty();
        repeat(20) @(negedge eth_clk);
        monitor_enable=1;
        for (batches=0; batches<2; batches=batches+1) begin
            for (tx_count=0; tx_count<256; tx_count=tx_count+1) begin
                @(negedge eth_clk); #0.5;
                tx_data=pattern(tx_count); tx_en=1; tx_er=((tx_count%4)==3);
            end
            @(negedge eth_clk); #0.5;
            tx_en=0; tx_er=0;
            repeat(12) @(negedge eth_clk);
            if (rx_count !== (batches+1)*256)
                $fatal(1,"[TB_ERROR] missing received bytes got=%0d",rx_count);
            if (batches==0) begin
                monitor_enable=0;
                rst_n=0;
                // Change the source while reset, then allow it to settle.
                ref125_high=4.4; #200;
                if (locked !== 1'b0) $fatal(1,"[TB_ERROR] lock did not clear on reset");
                rst_n=1;
                check_audio();
                check_eth_duty();
                repeat(20) @(negedge eth_clk);
                monitor_enable=1;
            end
        end
        $display("[TB_INFO] PASS: vendor GPLL frequency/relock, DIV2 duty shaping at 45/55%% source duty, 512 RGMII bytes, DDR order, RX_CTL error coding");
        $display("[TB_INFO] Simulation Finished!");
        $finish;
    end
    initial begin #50000; $fatal(1,"[TB_ERROR] board IO timeout"); end
endmodule
