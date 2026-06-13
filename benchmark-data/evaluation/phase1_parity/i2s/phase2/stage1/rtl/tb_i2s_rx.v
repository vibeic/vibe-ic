// =====================================================================
// tb_i2s_rx — self-checking testbench for the I2S receiver.
//
// Drives a known I2S frame (a left sample + a right sample, MSB-first,
// WS-change-one-SCK-before-MSB per spec) on SCK/WS/SD and checks the
// recovered parallel samples + valid strobes.
//
// Models a standard I2S TRANSMITTER as the stimulus:
//   * SCK is a free-running bit clock (modeled at a period that the
//     internal clk oversamples).
//   * WS changes one SCK period before the MSB of the next word.
//   * SD is driven MSB-first, two's-complement, updated on the SCK
//     falling edge (transmitter "may use either edge" — L8 — falling is
//     the conventional choice so data is stable across the receiver's
//     leading-edge latch).
//
// Tool: iverilog -g2012 + vvp.   PASS prints "TB PASS".
// =====================================================================

`timescale 1ns/1ps
`default_nettype none

module tb_i2s_rx;

    localparam integer WORD_WIDTH = 24;

    // internal sample clock: 100 MHz (10 ns) — oversamples the test SCK.
    localparam real CLK_PERIOD = 10.0;
    // test SCK period: 200 ns -> 20 internal clocks per SCK period -> 10x
    // oversample (well above the ~4x minimum).  Audio-realistic ratios are
    // far larger; 10x keeps the sim short while proving the CDC + edge det.
    localparam integer SCK_HALF = 100;  // ns half-period of SCK

    reg                    clk;
    reg                    rst_n;
    reg                    sck;
    reg                    ws;
    reg                    sd;

    wire [WORD_WIDTH-1:0]  left_data;
    wire [WORD_WIDTH-1:0]  right_data;
    wire                   left_valid;
    wire                   right_valid;

    integer errors;

    // captured-by-strobe holding regs for checking
    reg  [WORD_WIDTH-1:0]  got_left;
    reg  [WORD_WIDTH-1:0]  got_right;
    reg                    got_left_v;
    reg                    got_right_v;

    i2s_rx #(.WORD_WIDTH(WORD_WIDTH)) dut (
        .clk        (clk),
        .rst_n      (rst_n),
        .SCK        (sck),
        .WS         (ws),
        .SD         (sd),
        .left_data  (left_data),
        .right_data (right_data),
        .left_valid (left_valid),
        .right_valid(right_valid)
    );

    // internal sample clock
    initial clk = 1'b0;
    always #(CLK_PERIOD/2.0) clk = ~clk;

    // latch outputs whenever a valid strobe fires
    always @(posedge clk) begin
        if (left_valid)  begin got_left  <= left_data;  got_left_v  <= 1'b1; end
        if (right_valid) begin got_right <= right_data; got_right_v <= 1'b1; end
    end

    // ---- transmitter task: send ONE word (MSB-first) for channel `chan`
    // (chan: 0=left/WS=0, 1=right/WS=1).  Implements the I2S rule that WS
    // is set ONE SCK period before the MSB of this word. The caller sets WS
    // for THIS word on the SCK period preceding the first bit. ----
    task send_bit;
        input b;
        begin
            // drive SD on the (current) low phase, then clock high (leading
            // edge = receiver latch), then low again.
            sd = b;
            #(SCK_HALF);  sck = 1'b1;   // leading edge -> receiver latches
            #(SCK_HALF);  sck = 1'b0;   // trailing edge
        end
    endtask

    // send a full WORD_WIDTH-bit word MSB-first
    task send_word;
        input [WORD_WIDTH-1:0] word;
        integer i;
        begin
            for (i = WORD_WIDTH-1; i >= 0; i = i - 1) begin
                send_bit(word[i]);
            end
        end
    endtask

    reg [WORD_WIDTH-1:0] tx_left;
    reg [WORD_WIDTH-1:0] tx_right;

    initial begin
        $dumpfile("tb_i2s_rx.vcd");
        $dumpvars(0, tb_i2s_rx);

        errors      = 0;
        got_left_v  = 1'b0;
        got_right_v = 1'b0;
        got_left    = {WORD_WIDTH{1'b0}};
        got_right   = {WORD_WIDTH{1'b0}};

        // test vectors (two's complement audio samples)
        tx_left  = 24'h7A_3C_F1;   // arbitrary
        tx_right = 24'h81_00_55;   // negative-ish (MSB set)

        sck   = 1'b0;
        ws    = 1'b0;
        sd    = 1'b0;
        rst_n = 1'b0;
        #(CLK_PERIOD*5);
        rst_n = 1'b1;
        #(CLK_PERIOD*5);

        // --------------------------------------------------------------
        // I2S frame.  Per spec, WS for the UPCOMING word is set ONE SCK
        // period before that word's MSB.  We model continuous streaming:
        //
        //   ... drive WS=0 for one SCK period (no data bit consumed for
        //       this word yet — it's the "WS set" period) ...
        //
        // The simplest faithful model: keep streaming words back-to-back.
        // Before the LEFT word we hold WS=0 for one extra SCK period so the
        // receiver sees WS=0 stable, then the LEFT MSB.  The WS-change to
        // RIGHT happens one SCK period before the RIGHT MSB.
        // --------------------------------------------------------------

        // --- priming: hold WS=1 (opposite channel) for two SCK edges so
        // the receiver's ws_prev settles to 1.  The transition to WS=0
        // below then re-arms the accumulator cleanly for the LEFT word
        // (mirrors continuous streaming: a real bus is always mid-frame).
        ws = 1'b1;
        send_bit(1'b0);
        send_bit(1'b0);

        // --- WS changes to LEFT one SCK period before the LEFT MSB. This
        //     edge re-arms the accumulator (and would publish a prior RIGHT
        //     word, which here is the don't-care priming data — not checked).
        ws = 1'b0;
        send_bit(1'b0);            // WS-change edge: re-arm for LEFT

        // --- LEFT channel word (WS=0) ---
        ws = 1'b0;
        send_word(tx_left);

        // --- WS changes to RIGHT one SCK period before the RIGHT MSB.
        //     The act of changing WS on the next leading edge publishes the
        //     LEFT word.  send_bit here both carries the WS change and the
        //     "WS set" period (its SD bit is don't-care for the new word).
        ws = 1'b1;
        send_bit(1'b0);            // WS-change edge: LEFT published, re-arm

        // --- RIGHT channel word (WS=1) ---
        ws = 1'b1;
        send_word(tx_right);

        // --- WS changes back to LEFT one SCK period before next LEFT MSB,
        //     which publishes the RIGHT word. ---
        ws = 1'b0;
        send_bit(1'b0);            // WS-change edge: RIGHT published, re-arm

        // allow strobes to propagate through the internal clk domain
        #(CLK_PERIOD*40);

        // --------------------------------------------------------------
        // CHECKS
        // --------------------------------------------------------------
        if (!got_left_v) begin
            $display("FAIL: left_valid never asserted"); errors = errors + 1;
        end else if (got_left !== tx_left) begin
            $display("FAIL: left_data = %h expected %h", got_left, tx_left);
            errors = errors + 1;
        end else begin
            $display("OK  : left_data  = %h (expected %h)", got_left, tx_left);
        end

        if (!got_right_v) begin
            $display("FAIL: right_valid never asserted"); errors = errors + 1;
        end else if (got_right !== tx_right) begin
            $display("FAIL: right_data = %h expected %h", got_right, tx_right);
            errors = errors + 1;
        end else begin
            $display("OK  : right_data = %h (expected %h)", got_right, tx_right);
        end

        if (errors == 0) $display("TB PASS");
        else             $display("TB FAIL (%0d error(s))", errors);

        $finish;
    end

    // global timeout watchdog
    initial begin
        #(2_000_000);
        $display("FAIL: timeout");
        $finish;
    end

endmodule

`default_nettype wire
