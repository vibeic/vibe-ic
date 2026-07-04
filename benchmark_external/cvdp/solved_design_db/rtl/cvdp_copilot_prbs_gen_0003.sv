// Configurable PRBS generator / checker built around a parallel LFSR.
//   CHECK_MODE = 0 : generator -> data_out is the generated PRBS pattern.
//   CHECK_MODE = 1 : checker   -> data_out = data_in XOR locally-generated PRBS
//                                 (non-zero = a mismatch / error).
// One clock of latency from input to output. PRBS registers seed to all ones on reset.
//
// LFSR bit convention (matches the reference generator generate_prbs()):
//   feedback = prbs[POLY_LENGTH-POLY_TAP] ^ prbs[0]
//   next     = { feedback, prbs[POLY_LENGTH-1:1] }   (shift right, feedback into MSB)
//   output bit i = the i-th feedback bit produced this cycle.
//
// The checker uses an INDEPENDENT local LFSR (same seed / evolution as the
// generator) rather than loading data_in into the register, so a correct input
// stream produces zero error every cycle with no startup transient, for any
// POLY_LENGTH / WIDTH combination.
module cvdp_prbs_gen #(
    parameter CHECK_MODE  = 0,
    parameter POLY_LENGTH = 31,
    parameter POLY_TAP    = 3,
    parameter WIDTH       = 16
)(
    input  wire             clk,
    input  wire             rst,        // synchronous, active high
    input  wire [WIDTH-1:0] data_in,
    output reg  [WIDTH-1:0] data_out
);

    reg [POLY_LENGTH-1:0] prbs_reg;

    reg [POLY_LENGTH-1:0] prbs_v;
    reg [WIDTH-1:0]       prbs_bits;   // locally generated PRBS for this cycle
    reg                   feedback;
    integer               i;

    // Parallel unrolled LFSR: generate WIDTH PRBS bits per clock.
    always @(*) begin
        prbs_v    = prbs_reg;
        prbs_bits = {WIDTH{1'b0}};
        for (i = 0; i < WIDTH; i = i + 1) begin
            feedback     = prbs_v[POLY_LENGTH-POLY_TAP] ^ prbs_v[0];
            prbs_bits[i] = feedback;
            prbs_v       = {feedback, prbs_v[POLY_LENGTH-1:1]};
        end
    end

    always @(posedge clk) begin
        if (rst) begin
            prbs_reg <= {POLY_LENGTH{1'b1}};
            data_out <= {WIDTH{1'b1}};
        end else begin
            prbs_reg <= prbs_v;
            if (CHECK_MODE != 0)
                // Compare received data against the locally-generated PRBS.
                data_out <= data_in ^ prbs_bits;
            else
                // Emit the generated PRBS pattern.
                data_out <= prbs_bits;
        end
    end

endmodule
