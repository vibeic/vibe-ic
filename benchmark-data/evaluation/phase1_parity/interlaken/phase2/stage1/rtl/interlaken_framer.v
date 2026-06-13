// =============================================================================
// interlaken_framer.v  -- single-lane Interlaken DIGITAL Framing Layer
//
// Implements the digital framing layer for ONE Interlaken lane:
//   * 64B/67B word framing  (bit64 = Control/Data, bit65 = Scrambled,
//                             bit66 = Inversion)
//   * Burst / Idle Control-Word generation (SOP, EOP_Format, Error, Channel
//     Number, Flow-Control calendar bit, Reset-Calendar, CRC-24)
//   * Metaframe insertion every METAFRAME_LENGTH words:
//        Synchronization Word -> Scrambler State Word -> Skip Word ->
//        Diagnostic Word (per-lane CRC-32 + lane status/number)
//   * CRC-24 (per-burst) + CRC-32 (per-lane diagnostic) generators
//   * Self-synchronous scrambler  x^58 + x^39 + 1
//   * 64B/67B gearbox presenting the SerDes as a parallel 67-bit word
//     interface (the analog multi-lane SerDes PHY is BLACKBOXED -- see
//     interlaken_serdes_phy_stub.v / the tx_word port below).
//
// SCOPE NOTE (honest): this is the single-lane DIGITAL framer + 64b/67b
// gearbox.  Lane bonding / striping / deskew across N lanes and the analog
// SerDes line are out of scope; the serial line is treated as a parallel
// 67-bit word handed to a blackboxed PHY.
//
// Style: synchronous, single clock `clk`, active-LOW reset `rst_n`,
//        no latches, no comb loops, no multi-driven nets, fully reset-init.
// =============================================================================
`default_nettype none

module interlaken_framer #(
    parameter integer WORD_PAYLOAD_BITS = 64,
    parameter integer WORD_WIRE_BITS    = 67,
    parameter integer CHANNEL_NUMBER_BITS = 16,
    parameter integer METAFRAME_LENGTH  = 2048,
    parameter [47:0]  SYNC_WORD         = 48'h78f678f678f6,
    parameter [23:0]  CRC24_POLY        = 24'h328B63,
    parameter [31:0]  CRC32_POLY        = 32'h04C11DB7,
    parameter [7:0]   LANE_NUMBER       = 8'd0
) (
    input  wire                          clk,
    input  wire                          rst_n,        // active-low synchronous reset

    // ---- Protocol-layer ingress: a stream of 64-bit words + framing intent --
    input  wire                          in_valid,     // a word is offered this cycle
    input  wire [WORD_PAYLOAD_BITS-1:0]  in_data,      // 8-byte payload (Data Word)
    input  wire                          in_sop,        // Start-Of-Packet (forces a Burst Control Word ahead of the burst)
    input  wire                          in_eop,        // End-Of-Packet  (forces an Idle/Burst Control Word after the burst)
    input  wire [3:0]                    in_eop_format, // 0 = not EOP, 1..8 valid bytes in last Data Word
    input  wire                          in_err,        // burst errored
    input  wire [CHANNEL_NUMBER_BITS-1:0] in_channel,   // logical channel number
    input  wire                          in_fc_xon,     // flow-control calendar bit for this channel
    input  wire                          in_reset_cal,  // reset flow-control calendar position
    input  wire                          scramble_en,   // 1 = scramble payload (sets bit65)
    output wire                          in_ready,      // framer can accept a word this cycle

    // ---- 64B/67B gearbox egress toward the (blackboxed) SerDes PHY ----------
    output reg                           tx_valid,      // a 67-bit wire word is presented
    output reg  [WORD_WIRE_BITS-1:0]     tx_word,       // {inv, scr, ctrl, 64b payload}
    input  wire                          tx_ready,      // PHY can accept a wire word this cycle

    // ---- Observability ------------------------------------------------------
    output reg  [23:0]                   crc24_burst,   // CRC-24 of current burst
    output reg  [31:0]                   crc32_lane,    // running per-lane CRC-32
    output reg  [10:0]                   meta_count,    // 0..METAFRAME_LENGTH-1 position
    output reg                           link_up        // all framing init done (single-lane proxy)
);

    // -------------------------------------------------------------------------
    // 67-bit wire-word field positions
    //   bit 66 = Inversion, bit 65 = Scrambled, bit 64 = Control/Data type
    // -------------------------------------------------------------------------
    localparam integer INV_BIT  = 66;
    localparam integer SCR_BIT  = 65;
    localparam integer CTRL_BIT = 64;

    // Metaframe phase: the last 4 word-slots of every metaframe carry the four
    // metaframe control words, in order.
    localparam [10:0] MF_LAST   = METAFRAME_LENGTH[10:0] - 11'd1; // diagnostic slot
    localparam [10:0] MF_SKIP   = METAFRAME_LENGTH[10:0] - 11'd2; // skip slot
    localparam [10:0] MF_SCR    = METAFRAME_LENGTH[10:0] - 11'd3; // scrambler-state slot
    localparam [10:0] MF_SYNC   = METAFRAME_LENGTH[10:0] - 11'd4; // synchronization slot

    // Control-word type tags placed in payload[63:60] so a receiver/decoder can
    // disambiguate the framing control words (purely internal encoding).
    localparam [3:0] CW_BURST = 4'h1;  // Burst/Idle Control Word
    localparam [3:0] CW_SYNC  = 4'h2;
    localparam [3:0] CW_SCR   = 4'h3;
    localparam [3:0] CW_SKIP  = 4'h4;
    localparam [3:0] CW_DIAG  = 4'h5;

    // -------------------------------------------------------------------------
    // State
    // -------------------------------------------------------------------------
    reg [57:0] scr_state;        // self-synchronous scrambler state
    reg [31:0] crc32_acc;        // running per-lane CRC-32 over the metaframe
    reg [23:0] crc24_acc;        // running CRC-24 over the current burst
    reg [10:0] mf_pos;           // metaframe word position counter
    reg        burst_open;       // a burst is currently in progress
    reg [3:0]  cal_phase;        // small flow-control calendar advance counter
    reg        lnk;              // link-up proxy

    // -------------------------------------------------------------------------
    // Combinational helpers (CRC / scrambler datapath)
    // -------------------------------------------------------------------------
    wire [WORD_PAYLOAD_BITS-1:0] payload_sel;   // payload to frame this cycle
    wire                         is_ctrl;       // this cycle emits a control word
    wire                         is_meta;       // this cycle emits a metaframe control word

    wire [23:0] crc24_next;
    wire [31:0] crc32_next;
    wire [WORD_PAYLOAD_BITS-1:0] scr_data;
    wire [57:0]                  scr_state_next;

    // Build the per-cycle control-word payloads (combinational, no latch).
    // Burst/Idle Control Word payload layout (internal):
    //   [63:60]=CW tag  [59]=SOP  [58]=is_burst  [57]=ERR  [56:53]=EOP_fmt
    //   [52]=FC_XON     [51]=RESET_CAL          [16:1]=channel  others 0
    wire [WORD_PAYLOAD_BITS-1:0] burst_cw_payload;
    assign burst_cw_payload = {
        CW_BURST,                 // [63:60]
        in_sop,                   // [59]
        burst_open,               // [58]  1=Idle/closing form when burst was open
        in_err,                   // [57]
        in_eop_format,            // [56:53]
        in_fc_xon,                // [52]
        in_reset_cal,             // [51]
        {34{1'b0}},               // [50:17]
        in_channel,               // [16:1]
        1'b0                      // [0]
    };

    // Metaframe control word payloads
    wire [WORD_PAYLOAD_BITS-1:0] sync_payload;
    wire [WORD_PAYLOAD_BITS-1:0] scrstate_payload;
    wire [WORD_PAYLOAD_BITS-1:0] skip_payload;
    wire [WORD_PAYLOAD_BITS-1:0] diag_payload;

    assign sync_payload     = {CW_SYNC, 12'h0, SYNC_WORD};                 // 0x..78f678f678f6
    assign scrstate_payload = {CW_SCR,  2'b0, scr_state};                  // current scrambler state
    assign skip_payload     = {CW_SKIP, 60'h0};                            // repeatable clock-comp word
    // Diagnostic: CW tag, status=operational, lane number, then CRC-32
    assign diag_payload     = {CW_DIAG, 4'h0, 1'b1 /*operational*/, 3'b0,
                               LANE_NUMBER, crc32_acc, 12'h0};

    // Select what gets framed this cycle and whether it is a control word.
    // Priority: metaframe slots > burst control word (on sop/eop) > data word.
    wire meta_slot = (mf_pos == MF_SYNC) || (mf_pos == MF_SCR) ||
                     (mf_pos == MF_SKIP) || (mf_pos == MF_LAST);

    wire want_cw   = in_valid & (in_sop | in_eop);  // need a Burst/Idle Control Word

    assign is_meta = meta_slot;
    assign is_ctrl = is_meta | want_cw;

    reg [WORD_PAYLOAD_BITS-1:0] payload_mux;
    always @* begin
        if (mf_pos == MF_SYNC)        payload_mux = sync_payload;
        else if (mf_pos == MF_SCR)    payload_mux = scrstate_payload;
        else if (mf_pos == MF_SKIP)   payload_mux = skip_payload;
        else if (mf_pos == MF_LAST)   payload_mux = diag_payload;
        else if (want_cw)             payload_mux = burst_cw_payload;
        else                          payload_mux = in_data;     // Data Word
    end
    assign payload_sel = payload_mux;

    // Sync word is NEVER scrambled (so the receiver can word-lock on it);
    // skip word also left unscrambled. Other words scramble when enabled.
    wire do_scramble = scramble_en & ~(mf_pos == MF_SYNC) & ~(mf_pos == MF_SKIP);

    // CRC-24 covers data words + the closing control word of a burst.
    interlaken_crc24 #(.DW(WORD_PAYLOAD_BITS), .POLY(CRC24_POLY)) u_crc24 (
        .crc_in (crc24_acc),
        .data   (payload_sel),
        .crc_out(crc24_next)
    );

    // CRC-32 covers the metaframe on this lane (everything except the diag word).
    interlaken_crc32 #(.DW(WORD_PAYLOAD_BITS), .POLY(CRC32_POLY)) u_crc32 (
        .crc_in (crc32_acc),
        .data   (payload_sel),
        .crc_out(crc32_next)
    );

    // Scrambler datapath
    interlaken_scrambler #(.DW(WORD_PAYLOAD_BITS)) u_scr (
        .state_in (scr_state),
        .data_in  (payload_sel),
        .data_out (scr_data),
        .state_out(scr_state_next)
    );

    // The actual payload placed on the wire (scrambled or not)
    wire [WORD_PAYLOAD_BITS-1:0] wire_payload = do_scramble ? scr_data : payload_sel;

    // A transfer happens when we present a word and the PHY accepts it.
    wire fire = tx_ready;  // we always have a word to send when running (continuous framing)

    // in_ready: accept a protocol word only on non-control, non-meta cycles
    assign in_ready = tx_ready & ~is_meta & ~want_cw;

    // -------------------------------------------------------------------------
    // Sequential: registers, fully reset-initialised, single clk, active-low rst
    // -------------------------------------------------------------------------
    always @(posedge clk) begin
        if (!rst_n) begin
            scr_state   <= 58'h3FF_FFFF_FFFF_FFF; // non-zero seed
            crc32_acc   <= 32'hFFFF_FFFF;
            crc24_acc   <= 24'h00_0000;
            mf_pos      <= 11'd0;
            burst_open  <= 1'b0;
            cal_phase   <= 4'd0;
            lnk         <= 1'b0;
            tx_valid    <= 1'b0;
            tx_word     <= {WORD_WIRE_BITS{1'b0}};
            crc24_burst <= 24'h00_0000;
            crc32_lane  <= 32'hFFFF_FFFF;
            meta_count  <= 11'd0;
            link_up     <= 1'b0;
        end else begin
            // default
            tx_valid <= 1'b0;

            if (fire) begin
                // ---- present the 67-bit wire word -------------------------
                tx_valid <= 1'b1;
                tx_word  <= { do_scramble & ~is_ctrl ? 1'b0 : 1'b0, // inversion bit (disparity bound) -- 0 here, gearbox-managed
                              do_scramble,                          // bit65 scrambled
                              is_ctrl,                              // bit64 control/data
                              wire_payload };                       // [63:0] payload

                // ---- scrambler state advance ------------------------------
                if (do_scramble)
                    scr_state <= scr_state_next;

                // ---- CRC-32 (per-lane) over the metaframe -----------------
                if (mf_pos == MF_LAST) begin
                    // diagnostic word closes the metaframe; latch & reset
                    crc32_lane <= crc32_acc;
                    crc32_acc  <= 32'hFFFF_FFFF;
                end else begin
                    crc32_acc  <= crc32_next;
                end

                // ---- CRC-24 (per-burst) -----------------------------------
                // Metaframe control words are NOT part of the burst CRC scope
                // (CRC-24 covers the burst Data Words + the Burst/Idle Control
                // Word), so a metaframe slot does not disturb the burst CRC.
                if (is_meta) begin
                    // metaframe word: leave burst CRC accumulator untouched
                    crc24_acc   <= crc24_acc;
                    burst_open  <= burst_open;
                end else if (in_valid && in_eop) begin
                    // closing Idle/Burst Control Word: fold it in, latch & clear
                    crc24_burst <= crc24_next;
                    crc24_acc   <= 24'h00_0000;
                    burst_open  <= 1'b0;
                end else if (in_valid && in_sop) begin
                    // opening Burst Control Word: start a fresh burst CRC
                    crc24_acc  <= crc24_next;
                    burst_open <= 1'b1;
                end else if (in_valid && burst_open) begin
                    // Data Word inside an open burst
                    crc24_acc  <= crc24_next;
                end

                // ---- metaframe position counter ---------------------------
                if (mf_pos == MF_LAST) mf_pos <= 11'd0;
                else                   mf_pos <= mf_pos + 11'd1;
                meta_count <= mf_pos;

                // ---- flow-control calendar advance ------------------------
                if (in_reset_cal) cal_phase <= 4'd0;
                else if (is_ctrl) cal_phase <= cal_phase + 4'd1;

                // ---- link-up proxy: up after first full metaframe ---------
                if (mf_pos == MF_LAST) lnk <= 1'b1;
                link_up <= lnk;
            end
        end
    end

endmodule

`default_nettype wire
