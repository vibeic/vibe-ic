// =====================================================================
// tb_hdlc_octet_align — closing flag must land on an octet boundary
// ---------------------------------------------------------------------
// HDLC frames carried by this IP are an integral number of octets: rx_buf
// is a byte array, rx_len counts whole octets, and the receive FCS is
// folded one OCTET at a time.  Bits left over in a partial octet are
// therefore structurally OUTSIDE the FCS-covered region — no CRC vouches
// for them.  A receiver that accepts such a frame lets an extraneous or
// lost bit at the tail of a frame pass as a clean receive, which is
// exactly the error class the FCS exists to catch.
//
// Stimulus is built by an INDEPENDENT TB-side encoder (its own CRC-CCITT,
// its own zero-bit insertion), not by looping the DUT's own framer back,
// so a shared bug in the framer cannot mask a deframer bug.
//
// CHECK 1  well-formed frame            -> frame_valid=1, fcs_ok=1,
//                                          rx_len=4, payload exact,
//                                          rx_align_err=0
// CHECK 2  well-formed frame + ONE stray data bit before the closing flag.
//          The stray bit lands after the last complete octet, so the DUT
//          still folds exactly the right octets and the FCS RESIDUE STILL
//          MATCHES.  This is the case that makes the defect dangerous:
//          without an alignment check the frame presents as fully valid
//          (frame_valid=1, fcs_ok=1, rx_len=4).  It must be REJECTED.
// CHECK 3  2..7 stray bits              -> rejected, rx_align_err=1
// CHECK 4  well-formed frame AFTER a rejected one -> accepted (the reject
//          path must not wedge the receiver)
// CHECK 5  abort sequence               -> rx_abort=1 and rx_align_err=0
//          (the two error strobes must not be aliased onto each other)
//
// Compile with -DNO_ALIGN_ERR_PORT to run this SAME testbench against a
// pre-fix hdlc_core.v that has no rx_align_err output.  The frame_valid
// assertions — which are what CHECK 2/3/4 turn on — are identical in both
// modes; only the extra rx_align_err cross-checks are dropped.  That is
// what makes this regression reproducible: the pre-fix RTL fails CHECK 2.
//
// PASS prints "OCTET_ALIGN TB PASS"; any mismatch prints FAIL and $finish.
// Strobe rule: frame_valid / rx_align_err / rx_abort are 1-clk pulses and
// are latched by a concurrent always-block, never polled.
// =====================================================================
`timescale 1ns/1ps
`default_nettype none

module tb_hdlc_octet_align;
    localparam integer MAXB = 8;
    localparam integer IDXW = 4;

    reg              clk   = 1'b0;
    reg              rst_n = 1'b0;

    reg  [IDXW-1:0]  tx_len   = 0;
    reg  [7:0]       tx_wdata = 0;
    reg  [IDXW-1:0]  tx_waddr = 0;
    reg              tx_we    = 0;
    reg              tx_start = 0;
    wire             tx_busy, tx_done, tx_bit, tx_bit_valid;

    reg              rx_bit       = 1'b1;
    reg              rx_bit_valid = 1'b0;
    reg  [IDXW-1:0]  rx_raddr     = 0;
    wire [7:0]       rx_rdata;
    wire [IDXW-1:0]  rx_len;
    wire             frame_valid, fcs_ok, rx_abort, rx_idle, rx_overrun;
`ifndef NO_ALIGN_ERR_PORT
    wire             rx_align_err;
`endif

    hdlc_core #(.MAX_PAYLOAD_BYTES(MAXB), .IDXW(IDXW)) dut (
        .clk(clk), .rst_n(rst_n),
        .tx_len(tx_len), .tx_wdata(tx_wdata), .tx_waddr(tx_waddr),
        .tx_we(tx_we), .tx_start(tx_start), .tx_busy(tx_busy), .tx_done(tx_done),
        .tx_bit(tx_bit), .tx_bit_valid(tx_bit_valid),
        .rx_bit(rx_bit), .rx_bit_valid(rx_bit_valid),
        .rx_raddr(rx_raddr), .rx_rdata(rx_rdata), .rx_len(rx_len),
        .frame_valid(frame_valid), .fcs_ok(fcs_ok),
`ifndef NO_ALIGN_ERR_PORT
        .rx_align_err(rx_align_err),
`endif
        .rx_abort(rx_abort), .rx_idle(rx_idle), .rx_overrun(rx_overrun)
    );

    always #5 clk = ~clk;

    // ---- concurrent latch of the 1-clk strobes -----------------------
    reg            seen_valid = 1'b0;
    reg            seen_align = 1'b0;
    reg            seen_abort = 1'b0;
    reg            cap_fcs    = 1'b0;
    reg [IDXW-1:0] cap_len    = 0;
    always @(posedge clk) begin
        if (frame_valid && !seen_valid) begin
            seen_valid <= 1'b1;
            cap_fcs    <= fcs_ok;
            cap_len    <= rx_len;
        end
`ifndef NO_ALIGN_ERR_PORT
        if (rx_align_err) seen_align <= 1'b1;
`endif
        if (rx_abort) seen_abort <= 1'b1;
    end

    // ==================================================================
    //  Independent TB-side HDLC encoder
    // ==================================================================
    localparam [7:0] FLAGB = 8'h7E;

    reg  [7:0]  pay [0:7];
    integer     plen;
    reg [0:511] raw;     integer nraw;
    reg [0:511] wir;     integer nwir;
    integer     ones, t, i, errors;
    reg  [15:0] crc_acc;

    function [15:0] crc_step(input [15:0] crc, input dbit);
        reg fb;
        begin
            fb       = crc[15] ^ dbit;
            crc_step = {crc[14:0], 1'b0};
            if (fb) crc_step = crc_step ^ 16'h1021;
        end
    endfunction

    // Address+Control+Information, then the complemented FCS-16, LSB-first
    // per octet, then `stray` extra data bits.  Zeros are used for the
    // stray bits so they can never trigger zero-bit insertion themselves.
    task build_raw(input integer stray);
        integer j, m;
        reg [15:0] fcs;
        begin
            crc_acc = 16'hFFFF;
            for (j = 0; j < plen; j = j + 1)
                for (m = 7; m >= 0; m = m - 1) crc_acc = crc_step(crc_acc, pay[j][m]);
            fcs  = ~crc_acc;
            nraw = 0;
            for (j = 0; j < plen; j = j + 1)
                for (m = 0; m < 8; m = m + 1) begin raw[nraw] = pay[j][m];  nraw = nraw + 1; end
            for (m = 0; m < 8; m = m + 1)     begin raw[nraw] = fcs[8+m];   nraw = nraw + 1; end
            for (m = 0; m < 8; m = m + 1)     begin raw[nraw] = fcs[m];     nraw = nraw + 1; end
            for (m = 0; m < stray; m = m + 1) begin raw[nraw] = 1'b0;       nraw = nraw + 1; end
        end
    endtask

    // opening flag + zero-bit-inserted body + closing flag
    task build_wire;
        integer j;
        begin
            nwir = 0;
            for (j = 0; j < 8; j = j + 1) begin wir[nwir] = FLAGB[j]; nwir = nwir + 1; end
            ones = 0;
            for (j = 0; j < nraw; j = j + 1) begin
                wir[nwir] = raw[j]; nwir = nwir + 1;
                if (raw[j]) begin
                    ones = ones + 1;
                    if (ones == 5) begin wir[nwir] = 1'b0; nwir = nwir + 1; ones = 0; end
                end else ones = 0;
            end
            for (j = 0; j < 8; j = j + 1) begin wir[nwir] = FLAGB[j]; nwir = nwir + 1; end
        end
    endtask

    task feed;
        integer j;
        begin
            seen_valid = 1'b0; seen_align = 1'b0; seen_abort = 1'b0;
            rx_bit = 1'b1; rx_bit_valid = 1'b0;
            repeat (4) @(posedge clk);
            for (j = 0; j < nwir; j = j + 1) begin
                @(posedge clk); #1;
                rx_bit       = wir[j];
                rx_bit_valid = 1'b1;
            end
            @(posedge clk); #1; rx_bit_valid = 1'b0; rx_bit = 1'b1;
            repeat (6) @(posedge clk);
        end
    endtask

    // opening flag, a few data bits, then 8 ones => abort sequence
    task feed_abort;
        integer j;
        begin
            seen_valid = 1'b0; seen_align = 1'b0; seen_abort = 1'b0;
            nwir = 0;
            for (j = 0; j < 8; j = j + 1) begin wir[nwir] = FLAGB[j]; nwir = nwir + 1; end
            for (j = 0; j < 5; j = j + 1) begin wir[nwir] = 1'b0;     nwir = nwir + 1; end
            for (j = 0; j < 8; j = j + 1) begin wir[nwir] = 1'b1;     nwir = nwir + 1; end
            feed;
        end
    endtask

    task check_payload(input integer n);
        integer j;
        begin
            for (j = 0; j < n; j = j + 1) begin
                @(posedge clk); #1; rx_raddr = j[IDXW-1:0];
                @(posedge clk); #1;
                if (rx_rdata !== pay[j]) begin
                    $display("[TB] FAIL: byte[%0d]=%02h expected %02h", j, rx_rdata, pay[j]);
                    errors = errors + 1;
                end
            end
        end
    endtask

    initial begin
        errors = 0;
        pay[0] = 8'hC0; pay[1] = 8'h03; pay[2] = 8'hAA; pay[3] = 8'h55; plen = 4;

        repeat (4) @(posedge clk);
        rst_n = 1'b1;
        repeat (2) @(posedge clk);

        // ---- CHECK 1: well-formed frame is still accepted --------------
        build_raw(0); build_wire; feed;
        if (!seen_valid) begin
            $display("[TB] CHECK1 FAIL: well-formed frame not accepted (frame_valid never asserted)");
            errors = errors + 1;
        end else begin
            if (!cap_fcs) begin
                $display("[TB] CHECK1 FAIL: fcs_ok=0 on a well-formed frame"); errors = errors + 1;
            end
            if (cap_len !== plen[IDXW-1:0]) begin
                $display("[TB] CHECK1 FAIL: rx_len=%0d expected %0d", cap_len, plen); errors = errors + 1;
            end
            check_payload(plen);
        end
        if (seen_align) begin
            $display("[TB] CHECK1 FAIL: rx_align_err raised on a well-formed frame"); errors = errors + 1;
        end
        if (errors == 0) $display("[TB] CHECK1 PASS: aligned frame accepted, fcs_ok=1, len=%0d, payload exact", cap_len);

        // ---- CHECK 2: ONE stray bit, FCS residue still matches ---------
        build_raw(1); build_wire; feed;
        if (seen_valid) begin
            $display("[TB] CHECK2 FAIL: frame_valid=1 on a frame that ended mid-octet (fcs_ok=%0b, rx_len=%0d) -- the stray tail bit is outside the FCS-covered region and was silently discarded",
                     cap_fcs, cap_len);
            errors = errors + 1;
        end else
            $display("[TB] CHECK2 PASS: mid-octet close rejected (frame_valid stayed low)");
        if (!seen_align) begin
            $display("[TB] CHECK2 FAIL: rx_align_err not raised -- the frame was dropped with no reason given");
            errors = errors + 1;
        end else
            $display("[TB] CHECK2 PASS: rx_align_err raised, consumer told WHY");
        if (seen_abort) begin
            $display("[TB] CHECK2 FAIL: rx_abort raised for a misaligned close (error strobes aliased)");
            errors = errors + 1;
        end

        // ---- CHECK 3: 2..7 stray bits are all rejected -----------------
        for (t = 2; t <= 7; t = t + 1) begin
            build_raw(t); build_wire; feed;
            if (seen_valid) begin
                $display("[TB] CHECK3 FAIL: %0d stray bits accepted (frame_valid=1, rx_len=%0d)", t, cap_len);
                errors = errors + 1;
            end
            if (!seen_align) begin
                $display("[TB] CHECK3 FAIL: %0d stray bits -> no rx_align_err", t);
                errors = errors + 1;
            end
        end
        $display("[TB] CHECK3 done: 2..7 stray bits");

        // ---- CHECK 4: receiver recovers after a rejected frame ---------
        build_raw(0); build_wire; feed;
        if (!seen_valid || !cap_fcs || (cap_len !== plen[IDXW-1:0])) begin
            $display("[TB] CHECK4 FAIL: good frame after a rejected one not accepted (fv=%0b fcs_ok=%0b len=%0d)",
                     seen_valid, cap_fcs, cap_len);
            errors = errors + 1;
        end else
            $display("[TB] CHECK4 PASS: receiver resynced and accepted the next good frame");

        // ---- CHECK 5: abort is still its own distinct event ------------
        feed_abort;
        if (!seen_abort) begin
            $display("[TB] CHECK5 FAIL: abort sequence did not raise rx_abort"); errors = errors + 1;
        end
        if (seen_align) begin
            $display("[TB] CHECK5 FAIL: abort also raised rx_align_err (error strobes aliased)"); errors = errors + 1;
        end
        if (seen_valid) begin
            $display("[TB] CHECK5 FAIL: abort raised frame_valid"); errors = errors + 1;
        end
        $display("[TB] CHECK5 done: abort path");

        if (errors == 0) $display("OCTET_ALIGN TB PASS");
        else             $display("OCTET_ALIGN TB FAIL  (%0d errors)", errors);
        $finish;
    end

    initial begin
        #900000;
        $display("OCTET_ALIGN TB FAIL  (timeout)");
        $finish;
    end
endmodule

`default_nettype wire
