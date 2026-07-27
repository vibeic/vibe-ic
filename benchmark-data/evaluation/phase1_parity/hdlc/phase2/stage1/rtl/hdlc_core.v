// =====================================================================
// hdlc_core — HDLC Framer / Deframer IP block (ISO/IEC 13239)
// ---------------------------------------------------------------------
// Protocol : HDLC / SDLC bit-oriented synchronous data-link framing.
//            Flag-delimited frames, zero-bit insertion/deletion,
//            FCS-16 (CRC-CCITT) generation/checking, abort & idle
//            detection.  Bit-serial wire interface + a byte/CSR side.
// Source   : Phase-1 L-docs for benchmark_phase1/hdlc
//            (L1 datasheet, L3 cmd-protocol/frame-format, L4 regmap-notes,
//             L6 control-logic FSM hints, L8 RTL-constants, L9 integration)
//
// Function : Two independent engines sharing a byte/CSR interface.
//
//   TX (framer):  software writes the frame payload bytes (Address,
//     Control, Information) into a small payload buffer, drives tx_len,
//     and pulses tx_start.  The framer computes the 16-bit FCS
//     (CRC-CCITT, poly 0x1021, init 0xFFFF, output complemented) over
//     Address+Control+Information, then serialises:
//        opening FLAG 0x7E -> [payload+FCS with zero-bit insertion]
//        -> closing FLAG 0x7E.
//     Zero-bit insertion: after FIVE consecutive 1-bits in the
//     payload+FCS region a 0-bit is inserted, so a 0x7E flag can never
//     appear inside the frame body.  Flags are NEVER stuffed.       [L8]
//     Each octet is shifted LSB-first onto the wire.                [L3/L8]
//
//   RX (deframer):  watches the incoming serial bit stream, detects
//     the opening FLAG 0x7E, performs zero-bit deletion (after FIVE
//     consecutive 1-bits, strip the following 0-bit), detects ABORT
//     (>=7 consecutive 1-bits) and IDLE (>=15 consecutive 1-bits),
//     deserialises octets LSB-first into Address/Control/Information,
//     and on the closing FLAG checks BOTH octet alignment AND the FCS-16
//     residue (0x1D0F on a correct receive).  An octet-aligned close
//     raises frame_valid (1-clk) with fcs_ok; a close that lands mid-octet
//     raises rx_align_err (1-clk) instead and delivers nothing. [L6/L8]
//
// Spec grounding (every rule traceable to an L-doc):
//   * FLAG = 0x7E = binary 01111110.                                [L3 frame_field_layout, L8 FLAG_VALUE]
//   * Frame layout Flag|Address|Control|Information|FCS|Flag.        [L3 frame_field_layout]
//   * Bit-stuff threshold = 5 consecutive ones -> insert a 0.        [L8 BIT_STUFF_THRESHOLD]
//   * De-stuff: after 5 ones strip the 0; 6 ones then 0 => flag;     [L8 bit_destuff_pattern]
//     >=7 ones => abort.                                            [L8 abort_sequence_bits]
//   * Idle = continuous 1-bits (>=15 here) OR continuous flags.      [L3 interframe_state, L8 idle_pattern]
//   * FCS = CRC-CCITT poly 0x1021, init 0xFFFF, complemented out,    [L8 fcs_polynomial_default_crc_ccitt]
//     residue 0x1D0F on correct receive; covers Addr+Ctrl+Info.     [L8 coverage / residue]
//   * Wire bit order LSB-first within each octet.                   [L8 wire_bit_order, L3 byte_order]
//   * FSM TX_IDLE/OPEN_FLAG/.../CLOSE_FLAG ; RX_HUNT/FLAG_LOCKED/    [L6 fsm_hints_transmitter / receiver]
//     .../FCS_CHECK/DELIVER/ABORT.
//   * No protocol-layer register map; concrete IP defines its own    [L4 notes]
//     mode/status/FIFO CSR — we provide a minimal byte+status CSR.
//
// Octet-alignment decision — NOT DERIVABLE FROM THE L-DOCS (recorded here
// because the RTL depends on it and the spec is silent):
//   The source document is explicitly permissive — "Data is usually sent in
//   multiples of 8 bits, but only some variants require this; others
//   theoretically permit data alignments on other than 8-bit boundaries"
//   — and no L-doc names a non-integral-octet frame as an error.  L16
//   compliance_failure_modes lists only FCS_ERROR and ABORT_DETECTED for
//   the framing layer; L2 error_response_conditions likewise.
//   THIS IP implements the octet-aligned variant, and it has no choice:
//   rx_buf is a byte array, rx_len counts whole octets, and the receive
//   CRC is folded one OCTET at a time (crc16_byte), so bits left over in a
//   partial octet are structurally outside the FCS-covered region.  L2
//   performance_of_error_detection only claims CRC coverage "in the
//   FCS-covered region", so nothing in the design vouches for those bits.
//   Accepting such a frame would therefore let an extraneous or lost bit at
//   the tail of a frame pass with fcs_ok=1 — precisely the error class the
//   FCS exists to catch.  A close that does not land on an octet boundary
//   is consequently treated as an invalid frame: discarded, and reported
//   on rx_align_err.
//
// Implementation style : single-clock SYNCHRONOUS design.  Both engines
//   run in the chip's `clk` domain (Mode-0 bit clock: one wire bit per
//   clock when the engine is active, gated by *_bit_valid).  The RX
//   serial-receive shift engine uses ONE explicit bit counter
//   (rx_bit_cnt) as the sole source of octet-boundary / collect-enable
//   so the last bit cannot double-capture (serial-receive bit-counter
//   capture).  Reset is active-low synchronous on ALL state; every reg
//   is reset; no inferred latches (every case has a default; the FSM
//   default returns to a known state).
// =====================================================================

`timescale 1ns/1ps
`default_nettype none

module hdlc_core #(
    // Maximum payload (Address+Control+Information) bytes the TX framer
    // buffers and the RX deframer captures.  Small to stay PnR-friendly
    // while still exercising the full datapath.
    parameter integer MAX_PAYLOAD_BYTES = 8,
    // Index width: must hold 0..MAX_PAYLOAD_BYTES.  4 covers up to 15.
    parameter integer IDXW = 4
) (
    input  wire                          clk,
    input  wire                          rst_n,        // active-low sync reset

    // ----------------------------------------------------------------
    // TX byte/CSR side
    // ----------------------------------------------------------------
    input  wire [IDXW-1:0]               tx_len,       // payload bytes (Addr+Ctrl+Info)
    input  wire [7:0]                    tx_wdata,     // payload byte to load
    input  wire [IDXW-1:0]               tx_waddr,     // payload byte index to load
    input  wire                          tx_we,        // load strobe
    input  wire                          tx_start,     // 1-clk: begin framing
    output reg                           tx_busy,      // 1 while serialising a frame
    output reg                           tx_done,      // 1-clk strobe at end of frame

    // ----------------------------------------------------------------
    // Serial wire — TX out / RX in (Mode-0 bit clock: 1 wire bit/clk)
    // ----------------------------------------------------------------
    output reg                           tx_bit,       // serial line out (idle = 1)
    output reg                           tx_bit_valid, // 1 when tx_bit carries a frame bit
    input  wire                          rx_bit,       // serial line in
    input  wire                          rx_bit_valid, // 1 when rx_bit is a valid sample

    // ----------------------------------------------------------------
    // RX byte/CSR side + status
    // ----------------------------------------------------------------
    input  wire [IDXW-1:0]               rx_raddr,     // payload byte index to read
    output reg  [7:0]                    rx_rdata,     // captured payload byte
    output reg  [IDXW-1:0]               rx_len,       // payload bytes recovered (Addr+Ctrl+Info)
    output reg                           frame_valid,  // 1-clk strobe: a frame finished
    output reg                           fcs_ok,       // valid w/ frame_valid: FCS residue matched
    output reg                           rx_abort,     // 1-clk strobe: abort sequence seen
    output reg                           rx_align_err, // 1-clk strobe: closing flag landed mid-octet
    output reg                           rx_idle,      // level: line idle (>=15 ones)
    output reg                           rx_overrun    // sticky: payload exceeded buffer
);

    // Width of an index into the MAX_PAYLOAD_BYTES-deep buffers.
    localparam integer BIDX = (MAX_PAYLOAD_BYTES <= 1) ? 1 : $clog2(MAX_PAYLOAD_BYTES);

    localparam [7:0]  FLAG        = 8'h7E;       // 01111110                    [L8]
    localparam [15:0] CRC_POLY    = 16'h1021;    // CRC-CCITT X^16+X^12+X^5+1    [L8]
    localparam [15:0] CRC_INIT    = 16'hFFFF;    // initial register value      [L8]
    localparam [15:0] CRC_RESIDUE = 16'h1D0F;    // residue on correct receive  [L8]

    integer bi;

    // ----------------------------------------------------------------
    // Combinational CRC-CCITT one-bit step (MSB-first polynomial form):
    //   X^16+X^12+X^5+1.  Standard X.25/HDLC FCS feeds each byte MSB-first.
    // ----------------------------------------------------------------
    function [15:0] crc16_step;
        input [15:0] crc;
        input        data_bit;
        reg          fb;
        begin
            fb = crc[15] ^ data_bit;
            crc16_step = {crc[14:0], 1'b0};
            if (fb) crc16_step = crc16_step ^ CRC_POLY;
        end
    endfunction

    // Fold one octet (MSB-first) into the running CRC.  Pure function:
    // its internal blocking assigns are legitimate (no BLKSEQ).
    function [15:0] crc16_byte;
        input [15:0] crc;
        input [7:0]  octet;
        integer      b;
        reg   [15:0] c;
        begin
            c = crc;
            for (b = 7; b >= 0; b = b - 1)
                c = crc16_step(c, octet[b]);
            crc16_byte = c;
        end
    endfunction

    // TX payload buffer.  Declared HERE, ahead of tx_fcs_calc, because a
    // function may not reference an identifier declared later in the same
    // scope — with the declaration below the function, elaboration fails
    // with "Unable to bind wire/reg/memory `tx_buf[k]'".
    reg [7:0]      tx_buf [0:MAX_PAYLOAD_BYTES-1];

    // Pre-compute the transmit FCS over the loaded payload buffer:
    // CRC-CCITT, init 0xFFFF, MSB-first per byte, over the first `n`
    // payload bytes, then complemented (transmit_output_inversion).
    function [15:0] tx_fcs_calc;
        input [IDXW-1:0] n;
        integer          k;
        reg   [15:0]     c;
        begin
            c = CRC_INIT;
            for (k = 0; k < MAX_PAYLOAD_BYTES; k = k + 1)
                if (k < n) c = crc16_byte(c, tx_buf[k]);
            tx_fcs_calc = ~c;
        end
    endfunction

    // ================================================================
    //  TX FRAMER
    // ================================================================
    localparam [2:0] TX_IDLE  = 3'd0,
                     TX_OFLAG = 3'd1,   // opening flag
                     TX_BODY  = 3'd2,   // payload + FCS, with bit-stuffing
                     TX_CFLAG = 3'd3,   // closing flag
                     TX_FIN   = 3'd4;

    reg [2:0]      tx_state;
    reg [7:0]      tx_fcs_hi, tx_fcs_lo;     // complemented FCS bytes to send
    reg [IDXW:0]   tx_nbytes;                // payload byte count latched at start
    reg [IDXW:0]   tx_byte_idx;              // current body byte (payload then FCS)
    reg [2:0]      tx_bit_idx;               // 0..7 within an octet (LSB-first)
    reg [2:0]      tx_flag_idx;              // 0..7 within a flag octet
    reg [2:0]      tx_ones;                  // running consecutive-ones (stuffing)
    reg            tx_stuffing;              // emit a stuffed 0 this cycle
    reg            tx_last_pending;          // final body bit stuffed -> exit after the 0
    reg [7:0]      tx_cur_byte;              // body octet currently shifting
    wire [15:0]    tx_fcs_now = tx_fcs_calc(tx_len); // combinational FCS of loaded payload

    wire [IDXW:0] tx_body_bytes = tx_nbytes + {{(IDXW-1){1'b0}}, 2'd2}; // payload + 2 FCS

    // Current body octet select: 0..nbytes-1 payload, nbytes=FCS hi, nbytes+1=FCS lo.
    always @(*) begin
        if (tx_byte_idx < tx_nbytes)
            tx_cur_byte = tx_buf[tx_byte_idx[BIDX-1:0]];
        else if (tx_byte_idx == tx_nbytes)
            tx_cur_byte = tx_fcs_hi;
        else
            tx_cur_byte = tx_fcs_lo;
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            tx_state     <= TX_IDLE;
            tx_busy      <= 1'b0;
            tx_done      <= 1'b0;
            tx_bit       <= 1'b1;        // idle line = continuous ones
            tx_bit_valid <= 1'b0;
            tx_fcs_hi    <= 8'h00;
            tx_fcs_lo    <= 8'h00;
            tx_nbytes    <= {(IDXW+1){1'b0}};
            tx_byte_idx  <= {(IDXW+1){1'b0}};
            tx_bit_idx   <= 3'd0;
            tx_flag_idx  <= 3'd0;
            tx_ones      <= 3'd0;
            tx_stuffing  <= 1'b0;
            tx_last_pending <= 1'b0;
            // tx_crc_calc is a blocking-only scratch var (recomputed at
            // launch before any read); no reset needed.
            for (bi = 0; bi < MAX_PAYLOAD_BYTES; bi = bi + 1)
                tx_buf[bi] <= 8'h00;
        end else begin
            tx_done      <= 1'b0;
            tx_bit_valid <= 1'b0;
            tx_bit       <= 1'b1;        // default idle high unless driving a frame bit

            case (tx_state)
                // ----------------------------------------------------
                TX_IDLE: begin
                    tx_busy <= 1'b0;
                    if (tx_start) begin
                        // Pre-compute FCS over payload (MSB-first per byte,
                        // init 0xFFFF, complemented) via a pure function so
                        // the result can be latched with a single non-blocking
                        // assign (no in-process blocking scratch).
                        tx_fcs_hi   <= tx_fcs_now[15:8];
                        tx_fcs_lo   <= tx_fcs_now[7:0];
                        tx_nbytes   <= {1'b0, tx_len};
                        tx_byte_idx <= {(IDXW+1){1'b0}};
                        tx_flag_idx <= 3'd0;
                        tx_bit_idx  <= 3'd0;
                        tx_ones     <= 3'd0;
                        tx_stuffing <= 1'b0;
                        tx_last_pending <= 1'b0;
                        tx_busy     <= 1'b1;
                        tx_state    <= TX_OFLAG;
                    end
                end
                // ----------------------------------------------------
                TX_OFLAG: begin                                // opening flag, no stuffing
                    tx_bit       <= FLAG[tx_flag_idx];
                    tx_bit_valid <= 1'b1;
                    if (tx_flag_idx == 3'd7) begin
                        tx_flag_idx <= 3'd0;
                        tx_state    <= TX_BODY;
                        tx_ones     <= 3'd0;
                    end else begin
                        tx_flag_idx <= tx_flag_idx + 3'd1;
                    end
                end
                // ----------------------------------------------------
                TX_BODY: begin                                 // payload+FCS, LSB-first, stuffed
                    tx_bit_valid <= 1'b1;
                    if (tx_stuffing) begin
                        tx_bit      <= 1'b0;                   // inserted 0
                        tx_ones     <= 3'd0;
                        tx_stuffing <= 1'b0;
                        // If the stuff followed the FINAL body bit, leave
                        // to the closing flag now (the data is fully sent).
                        if (tx_last_pending) begin
                            tx_last_pending <= 1'b0;
                            tx_state        <= TX_CFLAG;
                        end
                    end else begin
                        tx_bit <= tx_cur_byte[tx_bit_idx];
                        if (tx_cur_byte[tx_bit_idx]) begin
                            if (tx_ones == 3'd4) begin
                                tx_ones     <= 3'd0;           // 5th one -> stuff next cycle
                                tx_stuffing <= 1'b1;
                            end else begin
                                tx_ones <= tx_ones + 3'd1;
                            end
                        end else begin
                            tx_ones <= 3'd0;
                        end
                        // The data bit was emitted THIS cycle, so advance
                        // to the next data bit unconditionally.  If a stuff
                        // is scheduled (tx_stuffing set above), the NEXT
                        // cycle emits the inserted 0 and holds (no advance)
                        // because it takes the tx_stuffing branch — so the
                        // 0 lands AFTER this 5th one and BEFORE the next
                        // data bit, exactly per the HDLC rule.
                        if (tx_bit_idx == 3'd7) begin
                            tx_bit_idx <= 3'd0;
                            if (tx_byte_idx == tx_body_bytes - 1'b1) begin
                                // Last body bit.  If it triggered a stuff,
                                // mark tx_last_pending so the stuff cycle
                                // leaves to the flag; else go now.
                                if (tx_cur_byte[tx_bit_idx] && (tx_ones == 3'd4))
                                    tx_last_pending <= 1'b1;
                                else
                                    tx_state <= TX_CFLAG;
                            end else begin
                                tx_byte_idx <= tx_byte_idx + 1'b1;
                            end
                        end else begin
                            tx_bit_idx <= tx_bit_idx + 3'd1;
                        end
                    end
                end
                // ----------------------------------------------------
                TX_CFLAG: begin                                // closing flag, no stuffing
                    tx_bit       <= FLAG[tx_flag_idx];
                    tx_bit_valid <= 1'b1;
                    if (tx_flag_idx == 3'd7) begin
                        tx_flag_idx <= 3'd0;
                        tx_state    <= TX_FIN;
                    end else begin
                        tx_flag_idx <= tx_flag_idx + 3'd1;
                    end
                end
                // ----------------------------------------------------
                TX_FIN: begin
                    tx_busy  <= 1'b0;
                    tx_done  <= 1'b1;
                    tx_state <= TX_IDLE;
                end
                // ----------------------------------------------------
                default: tx_state <= TX_IDLE;
            endcase

            // Payload load port (legal while idle).
            if (tx_we && (tx_waddr < MAX_PAYLOAD_BYTES[IDXW-1:0]))
                tx_buf[tx_waddr[BIDX-1:0]] <= tx_wdata;
        end
    end

    // ================================================================
    //  RX DEFRAMER  (canonical state-based de-stuffing)
    //  ONE explicit bit counter (rx_bit_cnt) is the sole octet-boundary
    //  source.  rx_ones counts consecutive 1-bits SEEN SO FAR (including
    //  the previous bit), and is the sole de-stuff / flag / abort detector:
    //    rx_ones==5, bit==0  -> destuffed 0 : DROP (do not collect)
    //    rx_ones==5, bit==1  -> 6th one     : candidate flag/abort, mark
    //    six_ones_pending, bit==0 -> FLAG    : frame boundary
    //    six_ones_pending, bit==1 -> >=7 ones: ABORT
    //  Otherwise the bit is a real data bit, assembled LSB-first.
    //  On FLAG, rx_bit_cnt is ALSO the octet-alignment witness: see
    //  rx_octet_aligned below.  A misaligned close is an invalid frame.
    // ================================================================
    localparam [1:0] RX_HUNT = 2'd0,   // search for opening flag
                     RX_RECV = 2'd1,   // collecting octets (de-stuffing)
                     RX_DONE = 2'd2;

    reg [7:0]    rx_buf [0:MAX_PAYLOAD_BYTES-1];
    reg [1:0]    rx_state;
    reg [7:0]    rx_shift;              // 8-bit sliding window (opening-flag hunt)
    reg [2:0]    rx_ones;               // consecutive 1-bits seen so far (sat at 7)
    reg          rx_six_pending;        // 6 ones seen, awaiting 0(flag)/1(abort)
    reg [2:0]    rx_bit_cnt;            // de-stuffed data bits in current octet (0..7)
    reg [7:0]    rx_octet;              // current octet assembled (LSB-first)
    reg [IDXW:0] rx_byte_cnt;           // Addr+Ctrl+Info+FCS octets collected
    reg [15:0]   rx_crc;                // running CRC over Addr+Ctrl+Info+FCS
    reg [15:0]   rx_idle_ones;          // long-run ones counter (idle detect)

    // sliding window read as an LSB-first octet (newest bit at top).
    wire [7:0] rx_window = {rx_bit, rx_shift[7:1]};
    // octet completed by the current de-stuffed data bit (LSB-first).
    wire [7:0] rx_full_octet = {rx_bit, rx_octet[7:1]};

    // ---- octet-alignment predicate at the closing flag ----------------
    // The closing flag 0x7E is 0 1 1 1 1 1 1 0 on the wire (LSB-first) and
    // is only RECOGNISED on its last bit, so by the time the flag is
    // disambiguated its first SIX bits — the leading 0 and the first five
    // 1s — have already been absorbed by the octet assembler as ordinary
    // data bits (the sixth 1 sets rx_six_pending and is not collected, and
    // the trailing 0 is the disambiguating bit).  A frame body that ended
    // exactly on an octet boundary therefore leaves rx_bit_cnt sitting at
    // exactly 6 when the flag is seen; ANY other value is the count of
    // residual body bits that did not fill an octet.  (Measured: aligned
    // -> 6; 1..7 stray bits -> 7,0,1,2,3,4,5 respectively — all distinct
    // from 6, so this predicate is exact, not approximate.)
    localparam [2:0] FLAG_PRECOLLECTED_BITS = 3'd6;
    wire rx_octet_aligned = (rx_bit_cnt == FLAG_PRECOLLECTED_BITS);

    always @(posedge clk) begin
        if (!rst_n) begin
            rx_state       <= RX_HUNT;
            rx_shift       <= 8'hFF;
            rx_ones        <= 3'd0;
            rx_six_pending <= 1'b0;
            rx_bit_cnt     <= 3'd0;
            rx_octet       <= 8'h00;
            rx_byte_cnt    <= {(IDXW+1){1'b0}};
            rx_crc         <= CRC_INIT;
            rx_len         <= {IDXW{1'b0}};
            frame_valid    <= 1'b0;
            fcs_ok         <= 1'b0;
            rx_abort       <= 1'b0;
            rx_align_err   <= 1'b0;
            rx_idle        <= 1'b0;
            rx_overrun     <= 1'b0;
            rx_idle_ones   <= 16'd0;
            // rx_crc_fold / rx_full_octet are blocking-only scratch vars
            // (assigned before read each cycle); no reset needed.
            for (bi = 0; bi < MAX_PAYLOAD_BYTES; bi = bi + 1)
                rx_buf[bi] <= 8'h00;
        end else begin
            frame_valid  <= 1'b0;       // 1-clk strobes default low
            rx_abort     <= 1'b0;
            rx_align_err <= 1'b0;

            if (rx_bit_valid) begin
                rx_shift <= rx_window;

                // ----- idle detector (>=15 continuous ones) ----------
                if (rx_bit) begin
                    if (rx_idle_ones != 16'hFFFF) rx_idle_ones <= rx_idle_ones + 16'd1;
                end else begin
                    rx_idle_ones <= 16'd0;
                end
                rx_idle <= (rx_idle_ones >= 16'd14) && rx_bit;

                // ----- consecutive-ones tracker ----------------------
                if (rx_bit)
                    rx_ones <= (rx_ones == 3'd7) ? 3'd7 : (rx_ones + 3'd1);
                else
                    rx_ones <= 3'd0;

                case (rx_state)
                    // ------------------------------------------------
                    RX_HUNT: begin
                        // Lock on the first complete 0x7E in the stream.
                        if (rx_window == FLAG) begin
                            rx_state       <= RX_RECV;
                            rx_bit_cnt     <= 3'd0;
                            rx_octet       <= 8'h00;
                            rx_byte_cnt    <= {(IDXW+1){1'b0}};
                            rx_crc         <= CRC_INIT;
                            rx_ones        <= 3'd0;
                            rx_six_pending <= 1'b0;
                            rx_overrun     <= 1'b0;
                        end
                    end
                    // ------------------------------------------------
                    RX_RECV: begin
                        if (rx_six_pending) begin
                            // 6 ones already seen; this bit disambiguates.
                            rx_six_pending <= 1'b0;
                            if (rx_bit == 1'b0) begin
                                // 0 1 1 1 1 1 1 0 = 0x7E -> closing flag.
                                if (rx_octet_aligned) begin
                                    frame_valid <= 1'b1;
                                    fcs_ok      <= (rx_crc == CRC_RESIDUE) &&
                                                   (rx_byte_cnt >= {{(IDXW-1){1'b0}}, 2'd2});
                                    if (rx_byte_cnt >= {{(IDXW-1){1'b0}}, 2'd2})
                                        rx_len <= rx_byte_cnt[IDXW-1:0] - {{(IDXW-2){1'b0}}, 2'd2};
                                    else
                                        rx_len <= {IDXW{1'b0}};
                                end else begin
                                    // Body did not end on an octet boundary.
                                    // The residual bits never completed an
                                    // octet, so they were never folded into
                                    // rx_crc and never written to rx_buf —
                                    // they are outside the FCS-covered
                                    // region and nothing vouches for them.
                                    // Delivering the frame here would let an
                                    // extraneous/lost tail bit pass as a
                                    // clean receive.  Discard it, and report
                                    // WHY on a strobe of its own rather than
                                    // aliasing rx_abort (a different line
                                    // event, counted separately) or lying
                                    // through fcs_ok (a different error).
                                    rx_align_err <= 1'b1;
                                    fcs_ok       <= 1'b0;
                                    rx_len       <= {IDXW{1'b0}};
                                end
                                rx_state <= RX_DONE;
                            end else begin
                                // 7+ consecutive ones -> ABORT.
                                rx_abort <= 1'b1;
                                rx_state <= RX_HUNT;
                                rx_shift <= 8'hFF;
                            end
                        end else if (rx_ones == 3'd5) begin
                            // Exactly five ones precede this bit.
                            if (rx_bit == 1'b0) begin
                                // De-stuffed 0 -> DROP (collect nothing).
                            end else begin
                                // Sixth one -> wait one more bit (flag/abort).
                                rx_six_pending <= 1'b1;
                            end
                        end else begin
                            // Normal de-stuffed data bit: assemble LSB-first.
                            // rx_full_octet is a combinational wire of the
                            // octet completed by this bit; folding it via the
                            // crc16_byte function keeps the always-block free
                            // of in-process blocking scratch.
                            if (rx_bit_cnt == 3'd7) begin
                                rx_bit_cnt <= 3'd0;
                                rx_octet   <= 8'h00;
                                if (rx_byte_cnt < MAX_PAYLOAD_BYTES[IDXW:0])
                                    rx_buf[rx_byte_cnt[BIDX-1:0]] <= rx_full_octet;
                                else
                                    rx_overrun <= 1'b1;
                                rx_crc      <= crc16_byte(rx_crc, rx_full_octet);
                                rx_byte_cnt <= rx_byte_cnt + 1'b1;
                            end else begin
                                rx_octet   <= rx_full_octet;
                                rx_bit_cnt <= rx_bit_cnt + 3'd1;
                            end
                        end
                    end
                    // ------------------------------------------------
                    RX_DONE: rx_state <= RX_HUNT;
                    // ------------------------------------------------
                    default: rx_state <= RX_HUNT;
                endcase
            end
        end
    end

    // RX read-back port (combinational read of the payload buffer).
    always @(*) begin
        if (rx_raddr < MAX_PAYLOAD_BYTES[IDXW-1:0])
            rx_rdata = rx_buf[rx_raddr[BIDX-1:0]];
        else
            rx_rdata = 8'h00;
    end

endmodule

`default_nettype wire
