// =============================================================================
// interlaken_serdes_phy_stub.v  -- BLACKBOX of the analog multi-lane SerDes PHY
//
// The real Interlaken PHY is an analog/mixed-signal multi-lane SerDes
// (6.25 / 10.3125 / 12.5 Gbps differential lanes). That is OUT OF SCOPE for
// this digital framer benchmark. We model it as a synthesizable digital stub
// that presents the SerDes to the framer as a PARALLEL 67-bit word interface:
// the framer hands it a 67-bit wire word, the stub asserts ready (a simple
// always-ready elastic-buffer proxy) and registers the word out on a parallel
// "symbol" bus. No analog behaviour is implied or modelled here.
//
// On real silicon this module would be replaced by the hard SerDes macro;
// keeping it as a clean digital port lets the framer synthesize and lint
// stand-alone.
// =============================================================================
`default_nettype none

module interlaken_serdes_phy_stub #(
    parameter integer WORD_WIRE_BITS = 67
) (
    input  wire                       clk,
    input  wire                       rst_n,
    // framer -> PHY
    input  wire                       tx_valid,
    input  wire [WORD_WIRE_BITS-1:0]  tx_word,
    output wire                       tx_ready,
    // PHY -> pins (parallel symbol bus -- blackboxed serial line)
    output reg                        sym_valid,
    output reg  [WORD_WIRE_BITS-1:0]  sym_word
);

    // Elastic-buffer proxy: always ready (single-lane, no back-pressure model).
    assign tx_ready = 1'b1;

    always @(posedge clk) begin
        if (!rst_n) begin
            sym_valid <= 1'b0;
            sym_word  <= {WORD_WIRE_BITS{1'b0}};
        end else begin
            sym_valid <= tx_valid;
            sym_word  <= tx_word;
        end
    end

endmodule

`default_nettype wire
