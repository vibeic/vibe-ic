// =============================================================================
// chip_top.v  -- top-level wrapper for the single-lane Interlaken Framer
//
// Wires the Interlaken digital Framing Layer (interlaken_framer) to a
// blackboxed parallel-symbol SerDes PHY stub (interlaken_serdes_phy_stub).
// Exposes the protocol's primary I/O at the chip boundary:
//   * protocol-layer ingress (64-bit word stream + framing intent)
//   * the 64B/67B gearbox egress as a parallel 67-bit "symbol" bus (the
//     analog serial SerDes line is blackboxed -- see the PHY stub).
//   * observability: per-burst CRC-24, per-lane CRC-32, metaframe position,
//     link-up.
//
// Single clock `clk`, active-LOW synchronous reset `rst_n`. No latches,
// no comb loops, no multi-driven nets; all state reset-initialised.
//
// SCOPE: single-lane DIGITAL framer only. Multi-lane bonding/striping/deskew
// and the analog SerDes are out of scope (PHY blackboxed).
// =============================================================================
`default_nettype none

module chip_top #(
    parameter integer WORD_PAYLOAD_BITS   = 64,
    parameter integer WORD_WIRE_BITS      = 67,
    parameter integer CHANNEL_NUMBER_BITS = 16,
    parameter integer METAFRAME_LENGTH    = 2048
) (
    input  wire                          clk,
    input  wire                          rst_n,

    // ---- Protocol-layer ingress --------------------------------------------
    input  wire                          in_valid,
    input  wire [WORD_PAYLOAD_BITS-1:0]  in_data,
    input  wire                          in_sop,
    input  wire                          in_eop,
    input  wire [3:0]                    in_eop_format,
    input  wire                          in_err,
    input  wire [CHANNEL_NUMBER_BITS-1:0] in_channel,
    input  wire                          in_fc_xon,
    input  wire                          in_reset_cal,
    input  wire                          scramble_en,
    output wire                          in_ready,

    // ---- Blackboxed SerDes parallel-symbol egress --------------------------
    output wire                          sym_valid,
    output wire [WORD_WIRE_BITS-1:0]     sym_word,

    // ---- Observability ------------------------------------------------------
    output wire [23:0]                   crc24_burst,
    output wire [31:0]                   crc32_lane,
    output wire [10:0]                   meta_count,
    output wire                          link_up
);

    // framer <-> PHY gearbox handshake
    wire                      tx_valid;
    wire [WORD_WIRE_BITS-1:0] tx_word;
    wire                      tx_ready;

    interlaken_framer #(
        .WORD_PAYLOAD_BITS  (WORD_PAYLOAD_BITS),
        .WORD_WIRE_BITS     (WORD_WIRE_BITS),
        .CHANNEL_NUMBER_BITS(CHANNEL_NUMBER_BITS),
        .METAFRAME_LENGTH   (METAFRAME_LENGTH)
    ) u_framer (
        .clk          (clk),
        .rst_n        (rst_n),
        .in_valid     (in_valid),
        .in_data      (in_data),
        .in_sop       (in_sop),
        .in_eop       (in_eop),
        .in_eop_format(in_eop_format),
        .in_err       (in_err),
        .in_channel   (in_channel),
        .in_fc_xon    (in_fc_xon),
        .in_reset_cal (in_reset_cal),
        .scramble_en  (scramble_en),
        .in_ready     (in_ready),
        .tx_valid     (tx_valid),
        .tx_word      (tx_word),
        .tx_ready     (tx_ready),
        .crc24_burst  (crc24_burst),
        .crc32_lane   (crc32_lane),
        .meta_count   (meta_count),
        .link_up      (link_up)
    );

    interlaken_serdes_phy_stub #(
        .WORD_WIRE_BITS(WORD_WIRE_BITS)
    ) u_phy (
        .clk      (clk),
        .rst_n    (rst_n),
        .tx_valid (tx_valid),
        .tx_word  (tx_word),
        .tx_ready (tx_ready),
        .sym_valid(sym_valid),
        .sym_word (sym_word)
    );

endmodule

`default_nettype wire
