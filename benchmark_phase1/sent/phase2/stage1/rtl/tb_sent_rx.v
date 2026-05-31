// =====================================================================
// tb_sent_rx — self-checking testbench: a NORMAL valid SENT frame.
//   Drives a synthesized SENT single-wire waveform (CAL pulse + status
//   nibble + 6 data nibbles + CORRECT CRC-4 nibble) into sent_rx and
//   checks: frame_valid asserts, crc_ok=1, decoded data nibbles match.
//   Tool substitution: iverilog 12 (-g2012) + vvp for Synopsys VCS.
// =====================================================================
`timescale 1ns/1ps
`default_nettype none

module tb_sent_rx;

    localparam integer NUM_DATA = 6;
    localparam integer PERIOD_W = 16;

    // ---- DUT clock: pick a clk much faster than one SENT tick ----
    // We model 1 SENT tick = TICK_CLK clk cycles.  Use a clean integer so
    // round(period/tick) is exact in the model.
    localparam integer TICK_CLK = 20;    // 20 clk cycles per SENT tick

    reg  clk = 1'b0;
    reg  rst_n = 1'b0;
    reg  sent_in = 1'b1;                  // line idles HIGH

    wire [4*NUM_DATA-1:0] data_nibbles;
    wire [3:0]            status_nibble;
    wire                  crc_ok;
    wire                  frame_valid;

    sent_rx #(.NUM_DATA_NIBBLES(NUM_DATA), .PERIOD_W(PERIOD_W)) dut (
        .clk(clk), .rst_n(rst_n), .sent_in(sent_in),
        .data_nibbles(data_nibbles), .status_nibble(status_nibble),
        .crc_ok(crc_ok), .frame_valid(frame_valid)
    );

    always #5 clk = ~clk;                 // 100 MHz model clock

    // ---- SAE J2716 CRC-4 reference (same table as the DUT) ----
    function [3:0] crc4_step;
        input [3:0] c; input [3:0] d; reg [3:0] i;
        begin
            i = c ^ d;
            case (i)
                4'd0:crc4_step=4'd0;4'd1:crc4_step=4'd13;4'd2:crc4_step=4'd7;4'd3:crc4_step=4'd10;
                4'd4:crc4_step=4'd14;4'd5:crc4_step=4'd3;4'd6:crc4_step=4'd9;4'd7:crc4_step=4'd4;
                4'd8:crc4_step=4'd1;4'd9:crc4_step=4'd12;4'd10:crc4_step=4'd6;4'd11:crc4_step=4'd11;
                4'd12:crc4_step=4'd15;4'd13:crc4_step=4'd2;4'd14:crc4_step=4'd8;default:crc4_step=4'd5;
            endcase
        end
    endfunction

    // ---- waveform driver: emit one pulse of `ticks` SENT-ticks ----
    // A pulse = falling edge, low for ~5 ticks, then high to fill the period;
    // the NEXT pulse's falling edge closes the period.  We drive: go low,
    // hold low MIN_LOW ticks, go high for the remainder, leaving the line
    // high; the subsequent emit_pulse's leading falling edge ends this period.
    localparam integer MIN_LOW = 5;
    task emit_pulse;
        input integer ticks;
        integer low_clks, high_clks, k;
        begin
            low_clks  = MIN_LOW * TICK_CLK;
            high_clks = (ticks - MIN_LOW) * TICK_CLK;
            sent_in = 1'b0;                            // falling edge
            for (k=0;k<low_clks;k=k+1)  @(posedge clk);
            sent_in = 1'b1;                            // rising
            for (k=0;k<high_clks;k=k+1) @(posedge clk);
        end
    endtask

    task emit_nibble; input [3:0] v; begin emit_pulse(12 + v); end endtask
    task emit_cal;                   begin emit_pulse(56);     end endtask

    integer n;
    reg [3:0] data_q [0:NUM_DATA-1];
    reg [3:0] crc_calc;
    reg [3:0] status_v;

    // Concurrent capture: frame_valid is a 1-clk pulse that can fire WHILE the
    // stimulus tasks are still driving, so latch it (and the outputs) the
    // instant it asserts rather than polling after the driver returns.
    reg              got_frame;
    reg              cap_crc_ok;
    reg [3:0]        cap_status;
    reg [4*NUM_DATA-1:0] cap_data;
    initial got_frame = 1'b0;
    always @(posedge clk) begin
        if (frame_valid && !got_frame) begin
            got_frame  <= 1'b1;
            cap_crc_ok <= crc_ok;
            cap_status <= status_nibble;
            cap_data   <= data_nibbles;
        end
    end

    initial begin
        $dumpfile("tb_sent_rx.vcd"); $dumpvars(0, tb_sent_rx);

        // data nibbles to send (first sent goes into [3:0] of data_nibbles)
        data_q[0]=4'h3; data_q[1]=4'hA; data_q[2]=4'h5;
        data_q[3]=4'h9; data_q[4]=4'hC; data_q[5]=4'h6;
        status_v = 4'h8;

        // reference CRC-4 over the 6 data nibbles, seed 5
        crc_calc = 4'd5;
        for (n=0;n<NUM_DATA;n=n+1) crc_calc = crc4_step(crc_calc, data_q[n]);

        // reset
        repeat (10) @(posedge clk);
        rst_n = 1'b1;
        repeat (5) @(posedge clk);

        // ---- drive one valid frame ----
        // Need an extra closing falling edge to terminate the CRC pulse's
        // period; we emit a trailing CAL pulse to both close CRC and start
        // (harmlessly) a resync.
        emit_cal();                                    // calibration (56 ticks)
        emit_nibble(status_v);                         // status nibble
        for (n=0;n<NUM_DATA;n=n+1) emit_nibble(data_q[n]); // data nibbles
        emit_nibble(crc_calc);                         // CRC nibble
        emit_cal();                                    // closes CRC period + resync

        // wait for the latched frame
        n = 0;
        while (got_frame !== 1'b1 && n < 200000) begin @(posedge clk); n=n+1; end

        if (got_frame !== 1'b1) begin
            $display("TB FAIL: frame_valid never asserted"); $finish;
        end
        $display("frame_valid=1  crc_ok=%b  status=%h  data=%h",
                 cap_crc_ok, cap_status, cap_data);

        if (cap_crc_ok !== 1'b1) begin
            $display("TB FAIL: crc_ok=%b expected 1 (crc_calc=%h)", cap_crc_ok, crc_calc);
            $finish;
        end
        if (cap_status !== status_v) begin
            $display("TB FAIL: status=%h expected %h", cap_status, status_v); $finish;
        end
        for (n=0;n<NUM_DATA;n=n+1) begin
            if (cap_data[4*n +: 4] !== data_q[n]) begin
                $display("TB FAIL: data nibble %0d = %h expected %h",
                         n, cap_data[4*n +: 4], data_q[n]); $finish;
            end
        end

        $display("TB PASS  (status=%h data=%h crc_ok=1)", cap_status, cap_data);
        $finish;
    end

    initial begin #50_000_000 $display("TB FAIL: global timeout"); $finish; end

endmodule

`default_nettype wire
