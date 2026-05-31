// =====================================================================
// tb_hdlc_stuff_fcserr — zero-bit-stuffing edge case + FCS-error case
// ---------------------------------------------------------------------
// TEST 1 (stuffing edge case): a payload 0xFF 0x7E 0x7D — bytes packed
//   with the bit pattern that forces MULTIPLE zero-stuffs (0xFF is eight
//   ones; 0x7E/0x7D each carry a six-ones flag-like run) — is framed,
//   the serialised bitstream is checked to contain NO 6-ones run in the
//   body (every five-ones run was broken by an inserted 0), and the
//   deframer must recover the exact 3 payload bytes with fcs_ok=1.
//
// TEST 2 (FCS-error case): the SAME good bitstream is replayed but with
//   one payload bit flipped before the FCS, so the FCS-16 residue no
//   longer matches.  The deframer must still complete the frame
//   (frame_valid=1) but raise fcs_ok=0 — error flagged, not silently
//   accepted.
//
// PASS prints "STUFF_FCSERR TB PASS"; any mismatch prints FAIL + $finish.
// Strobe rule: frame_valid (1-clk) is latched concurrently, never polled.
// =====================================================================
`timescale 1ns/1ps
`default_nettype none

module tb_hdlc_stuff_fcserr;
    localparam integer MAXB = 8;
    localparam integer IDXW = 4;

    reg               clk = 1'b0;
    reg               rst_n = 1'b0;
    reg  [IDXW-1:0]   tx_len   = 0;
    reg  [7:0]        tx_wdata = 0;
    reg  [IDXW-1:0]   tx_waddr = 0;
    reg               tx_we    = 0;
    reg               tx_start = 0;
    wire              tx_busy, tx_done, tx_bit, tx_bit_valid;
    reg               rx_bit       = 1'b1;
    reg               rx_bit_valid = 1'b0;
    reg  [IDXW-1:0]   rx_raddr     = 0;
    wire [7:0]        rx_rdata;
    wire [IDXW-1:0]   rx_len;
    wire              frame_valid, fcs_ok, rx_abort, rx_idle, rx_overrun;

    hdlc_core #(.MAX_PAYLOAD_BYTES(MAXB), .IDXW(IDXW)) dut (
        .clk(clk), .rst_n(rst_n),
        .tx_len(tx_len), .tx_wdata(tx_wdata), .tx_waddr(tx_waddr),
        .tx_we(tx_we), .tx_start(tx_start), .tx_busy(tx_busy), .tx_done(tx_done),
        .tx_bit(tx_bit), .tx_bit_valid(tx_bit_valid),
        .rx_bit(rx_bit), .rx_bit_valid(rx_bit_valid),
        .rx_raddr(rx_raddr), .rx_rdata(rx_rdata), .rx_len(rx_len),
        .frame_valid(frame_valid), .fcs_ok(fcs_ok),
        .rx_abort(rx_abort), .rx_idle(rx_idle), .rx_overrun(rx_overrun)
    );

    always #5 clk = ~clk;

    // concurrent latch of the 1-clk frame_valid pulse
    reg            seen_valid = 1'b0;
    reg            cap_fcs_ok = 1'b0;
    reg [IDXW-1:0] cap_len    = 0;
    always @(posedge clk) begin
        if (frame_valid && !seen_valid) begin
            seen_valid <= 1'b1;
            cap_fcs_ok <= fcs_ok;
            cap_len    <= rx_len;
        end
    end

    // capture TX bitstream
    reg [0:255] cap_bits;
    integer     cap_n = 0;
    always @(posedge clk) begin
        if (tx_bit_valid && (cap_n < 256)) begin
            cap_bits[cap_n] <= tx_bit;
            cap_n           <= cap_n + 1;
        end
    end

    reg [7:0] payload [0:2];
    integer   plen = 3;
    integer   i, k, ones, flag_inside, errors;

    task load_byte(input [IDXW-1:0] a, input [7:0] d);
        begin
            @(posedge clk); #1; tx_waddr = a; tx_wdata = d; tx_we = 1'b1;
            @(posedge clk); #1; tx_we = 1'b0;
        end
    endtask

    task feed_stream(input integer flip_idx);  // flip_idx<0 => no flip
        begin
            seen_valid = 1'b0;
            rx_bit = 1'b1; rx_bit_valid = 1'b0;
            repeat (4) @(posedge clk);
            for (k = 0; k < cap_n; k = k + 1) begin
                @(posedge clk); #1;
                rx_bit       = (k == flip_idx) ? ~cap_bits[k] : cap_bits[k];
                rx_bit_valid = 1'b1;
            end
            @(posedge clk); #1; rx_bit_valid = 1'b0; rx_bit = 1'b1;
            repeat (6) @(posedge clk);
        end
    endtask

    initial begin
        errors = 0;
        payload[0] = 8'hFF;   // eight ones -> forces a stuff
        payload[1] = 8'h7E;   // flag-like body byte -> forces a stuff
        payload[2] = 8'h7D;   // escape-like body byte -> forces a stuff

        repeat (4) @(posedge clk);
        rst_n = 1'b1;
        repeat (2) @(posedge clk);

        for (i = 0; i < plen; i = i + 1) load_byte(i[IDXW-1:0], payload[i]);
        @(posedge clk); #1; tx_len = plen[IDXW-1:0]; tx_start = 1'b1;
        @(posedge clk); #1; tx_start = 1'b0;
        wait (tx_done == 1'b1);
        repeat (3) @(posedge clk);
        $display("[TB] captured %0d serial bits for payload FF 7E 7D", cap_n);

        // ---- TEST 1: stuffing edge case ----------------------------
        // No 6-ones run anywhere in the body proves multiple stuffs fired.
        flag_inside = 0; ones = 0;
        for (k = 8; k < cap_n - 8; k = k + 1) begin
            if (cap_bits[k]) begin
                ones = ones + 1;
                if (ones >= 6) flag_inside = 1;
            end else ones = 0;
        end
        if (flag_inside) begin
            $display("[TB] TEST1 FAIL: 6+ ones in body (stuffing failed for FF/7E/7D)");
            errors = errors + 1;
        end else
            $display("[TB] TEST1 OK: zero-bit insertion broke every 5-ones run (no body flag)");

        feed_stream(-1);   // clean replay

        if (!seen_valid) begin
            $display("[TB] TEST1 FAIL: frame_valid never asserted"); errors = errors + 1;
        end else begin
            if (!cap_fcs_ok) begin
                $display("[TB] TEST1 FAIL: fcs_ok=0 on good frame"); errors = errors + 1;
            end
            if (cap_len !== plen[IDXW-1:0]) begin
                $display("[TB] TEST1 FAIL: rx_len=%0d expected %0d", cap_len, plen);
                errors = errors + 1;
            end
            for (i = 0; i < plen; i = i + 1) begin
                @(posedge clk); #1; rx_raddr = i[IDXW-1:0];
                @(posedge clk); #1;
                if (rx_rdata !== payload[i]) begin
                    $display("[TB] TEST1 FAIL: byte[%0d]=%02h expected %02h", i, rx_rdata, payload[i]);
                    errors = errors + 1;
                end else
                    $display("[TB] TEST1 byte[%0d]=%02h OK", i, rx_rdata);
            end
            if (errors == 0)
                $display("[TB] TEST1 PASS: FF 7E 7D round-tripped with multiple stuffs, fcs_ok=1");
        end

        // ---- TEST 2: FCS-error case --------------------------------
        // Replay the same stream but flip one data bit (index 12, inside
        // the first payload byte region after the opening flag).  The
        // frame must still complete but fcs_ok must be 0.
        feed_stream(12);

        if (!seen_valid) begin
            $display("[TB] TEST2 FAIL: frame_valid never asserted on corrupted frame");
            errors = errors + 1;
        end else if (cap_fcs_ok) begin
            $display("[TB] TEST2 FAIL: fcs_ok=1 on a corrupted frame (error not detected)");
            errors = errors + 1;
        end else
            $display("[TB] TEST2 PASS: corrupted frame completed (frame_valid=1) with fcs_ok=0");

        if (errors == 0)
            $display("STUFF_FCSERR TB PASS");
        else
            $display("STUFF_FCSERR TB FAIL  (%0d errors)", errors);
        $finish;
    end

    initial begin
        #400000;
        $display("STUFF_FCSERR TB FAIL  (timeout)");
        $finish;
    end
endmodule

`default_nettype wire
