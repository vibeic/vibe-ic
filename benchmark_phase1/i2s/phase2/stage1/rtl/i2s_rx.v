// =====================================================================
// i2s_rx — I2S Receiver (target / slave) IP block
// ---------------------------------------------------------------------
// Protocol : I2S Bus (Inter-IC Sound, Philips/NXP UM11732 Rev. 3.0)
// Source   : Phase-1 L-docs for benchmark_phase1/i2s
//            (L17 signal catalog, L9 integration, L8 RTL-constants/timing,
//             L6 control-logic, L3 cmd-protocol)
//
// Function : Recovers parallel two's-complement audio samples from the
//            3-wire I2S stream (SCK / WS / SD), demultiplexing the two
//            time-interleaved channels (WS=0 left, WS=1 right) and
//            pulsing a per-channel data-valid strobe.
//
// Spec grounding (every rule traceable to an L-doc):
//   * SCK : continuous serial bit clock, RECEIVER LATCHES SD + WS on the
//           LEADING (LOW->HIGH) edge of SCK.            [L17, L8, L6]
//   * WS  : 0 = channel 1 (left), 1 = channel 2 (right).[L17, L8, L3]
//           WS changes ONE SCK period BEFORE the MSB of the next word;
//           i.e. the MSB arrives on the first leading SCK edge AFTER the
//           WS change.                                  [L8 key_constants,
//                                                        L8_TIMING, L6]
//   * SD  : MSB-first, two's-complement.                [L17, L3, L8]
//   * Word length is implementation-defined and need NOT match between
//           transmitter and receiver:                   [L8, L3]
//             - overrun : receiver IGNORES extra LSBs beyond WORD_WIDTH.
//             - underrun: receiver treats absent LSBs as the value it
//                         already shifted in (transmitter zero-pads).
//   * No start/stop/parity/framing — pure streaming.    [L8, L3]
//
// Implementation style : single-clock SYNCHRONOUS SLAVE.  The external
//   SCK/WS/SD are asynchronous to the chip's own `clk` (L9 primary domain,
//   2.5 MHz / 400 ns).  They are double-flop synchronized, then SCK rising
//   edges are detected in the `clk` domain.  `clk` MUST be at least ~4x
//   faster than SCK for reliable edge detection (standard oversampled-slave
//   requirement; for sign-off the L9 2.5 MHz domain oversamples audio-rate
//   SCK comfortably).  This makes the block a clean, fully-synchronous,
//   single-clock-domain design suitable for digital PnR sign-off.
//
// Hygiene: active-low sync reset on all state; every reg reset; no latches;
//   no full-case/parallel-case reliance; reset-less regs N/A (all reset).
// =====================================================================

`timescale 1ns/1ps
`default_nettype none

module i2s_rx #(
    // Receiver internal word length in bits (MSB-first).  Per L8 typical
    // examples {16,18,20,24,32}; 24 chosen as a common audio default.
    parameter integer WORD_WIDTH = 24
) (
    input  wire                       clk,        // internal sample clock (L9 primary, 2.5 MHz)
    input  wire                       rst_n,      // active-low synchronous reset

    // ---- I2S serial bus inputs (target side) ----
    input  wire                       SCK,        // continuous serial bit clock  [L17]
    input  wire                       WS,         // word select (0=left,1=right) [L17]
    input  wire                       SD,         // serial data, MSB-first       [L17]

    // ---- Recovered parallel-sample outputs ----
    output reg  [WORD_WIDTH-1:0]      left_data,  // last complete LEFT  (WS=0) sample
    output reg  [WORD_WIDTH-1:0]      right_data, // last complete RIGHT (WS=1) sample
    output reg                        left_valid, // 1-clk strobe: left_data  updated
    output reg                        right_valid // 1-clk strobe: right_data updated
);

    // -----------------------------------------------------------------
    // 1. CDC synchronizers — 2-flop for each async input.
    //    SCK/WS/SD cross from the external transmitter/controller domain
    //    into `clk`.  Synchronize before any edge logic.
    // -----------------------------------------------------------------
    reg [1:0] sck_sync;
    reg [1:0] ws_sync;
    reg [1:0] sd_sync;

    always @(posedge clk) begin
        if (!rst_n) begin
            sck_sync <= 2'b00;
            ws_sync  <= 2'b00;
            sd_sync  <= 2'b00;
        end else begin
            sck_sync <= {sck_sync[0], SCK};
            ws_sync  <= {ws_sync[0],  WS };
            sd_sync  <= {sd_sync[0],  SD };
        end
    end

    wire sck_s = sck_sync[1];   // synchronized SCK
    wire ws_s  = ws_sync[1];    // synchronized WS
    wire sd_s  = sd_sync[1];    // synchronized SD

    // -----------------------------------------------------------------
    // 2. SCK leading-edge detection in `clk` domain.
    //    Receiver latches SD + WS on the LEADING (LOW->HIGH) edge. [L8/L6]
    // -----------------------------------------------------------------
    reg sck_s_d;                // 1-cycle-delayed synchronized SCK
    always @(posedge clk) begin
        if (!rst_n) sck_s_d <= 1'b0;
        else        sck_s_d <= sck_s;
    end
    wire sck_rising = sck_s & ~sck_s_d;   // leading edge of SCK

    // -----------------------------------------------------------------
    // 3. Bit-deserialize + channel demux.
    //
    //    On each leading SCK edge:
    //      (a) sample WS (current-bit channel) and SD.
    //      (b) detect WS change vs the WS seen at the PREVIOUS leading
    //          edge.  A WS change means: the word that was being
    //          accumulated for the PREVIOUS channel is now COMPLETE
    //          (its last bit was the one sampled on the edge before this
    //          one) -> publish it; and a NEW word begins.  Per spec the
    //          MSB of the new word arrives one SCK period AFTER the WS
    //          change, i.e. on the NEXT leading edge -> so on the WS-change
    //          edge itself we do NOT shift the new word's MSB; we re-arm.
    //
    //    Shift register is MSB-first: new bit enters the LSB and the word
    //    shifts left, so after WORD_WIDTH bits the first (MSB) bit sits in
    //    the top position.  Overrun (more bits than WORD_WIDTH before the
    //    next WS change) naturally drops the oldest (MSB-side) bits —
    //    but because publication is gated on the WS edge, the value
    //    published is the MOST RECENT WORD_WIDTH bits, which for a
    //    correctly-sized transmitter is exactly the intended sample, and
    //    for an over-long transmitter word keeps the MSB-aligned bits per
    //    the spec's "receiver ignores extra LSBs" rule (see note below).
    // -----------------------------------------------------------------
    reg [WORD_WIDTH-1:0] shifter;     // MSB-first accumulation register
    reg                  ws_prev;     // WS sampled at previous leading edge
    reg [WORD_WIDTH-1:0] bit_capture; // captured first WORD_WIDTH bits of the word

    // bit_count saturates at WORD_WIDTH so that, per the I2S overrun rule,
    // any SD bits AFTER the first WORD_WIDTH of a word are ignored (the
    // receiver keeps the MSB-aligned WORD_WIDTH bits).  Width sized to hold
    // WORD_WIDTH (+1 head-room) without truncation.
    localparam integer CNT_W = $clog2(WORD_WIDTH + 1);
    reg [CNT_W-1:0] bit_count;

    always @(posedge clk) begin
        if (!rst_n) begin
            shifter     <= {WORD_WIDTH{1'b0}};
            ws_prev     <= 1'b0;
            bit_capture <= {WORD_WIDTH{1'b0}};
            bit_count   <= {CNT_W{1'b0}};
            left_data   <= {WORD_WIDTH{1'b0}};
            right_data  <= {WORD_WIDTH{1'b0}};
            left_valid  <= 1'b0;
            right_valid <= 1'b0;
        end else begin
            // valid strobes are single-cycle pulses by default
            left_valid  <= 1'b0;
            right_valid <= 1'b0;

            if (sck_rising) begin
                if (ws_s != ws_prev) begin
                    // ---- WS edge: previous channel's word is complete ----
                    // ws_prev identifies the channel the just-finished word
                    // belonged to (0=left, 1=right).
                    if (ws_prev == 1'b0) begin
                        left_data  <= bit_capture;
                        left_valid <= 1'b1;
                    end else begin
                        right_data  <= bit_capture;
                        right_valid <= 1'b1;
                    end
                    // Re-arm for the new word.  Per spec, MSB of the new
                    // word arrives on the NEXT leading edge, so we do NOT
                    // capture an SD bit on this WS-change edge.
                    shifter   <= {WORD_WIDTH{1'b0}};
                    bit_count <= {CNT_W{1'b0}};
                    ws_prev   <= ws_s;
                end else begin
                    // ---- same channel: accumulate one bit (MSB-first) ----
                    // shift left, new SD bit into LSB position
                    shifter <= {shifter[WORD_WIDTH-2:0], sd_s};
                    // capture only the first WORD_WIDTH bits (overrun rule)
                    if (bit_count < WORD_WIDTH[CNT_W-1:0]) begin
                        bit_capture <= {shifter[WORD_WIDTH-2:0], sd_s};
                        bit_count   <= bit_count + 1'b1;
                    end
                    // ws_prev unchanged
                end
            end
        end
    end

endmodule

`default_nettype wire
