// Manchester Encoder — latch-inference bug fixed by registering the output
// with an explicit else that drives the spec-mandated 0 when idle.
//
// Encoding convention (MSB-first, IEEE 802.3): each data bit becomes two
// line bits.  data bit 0 -> 2'b10 , data bit 1 -> 2'b01.
// enc_data_in[N-1] maps to enc_data_out[2N-1:2N-2].
module manchester_encoder #(
    parameter N = 8
)(
    input  wire            clk_in,
    input  wire            rst_in,        // active-high synchronous reset
    input  wire            enc_valid_in,
    input  wire [N-1:0]    enc_data_in,
    output reg             enc_valid_out,
    output reg  [2*N-1:0]  enc_data_out
);

    integer k;
    reg [2*N-1:0] enc_comb;

    // Combinational Manchester map of the current input word.
    always @(*) begin
        enc_comb = {(2*N){1'b0}};
        for (k = 0; k < N; k = k + 1) begin
            // bit 0 -> "10", bit 1 -> "01"
            enc_comb[2*k +: 2] = enc_data_in[k] ? 2'b01 : 2'b10;
        end
    end

    // Registered outputs.  Every branch assigns both outputs, so no latch is
    // inferred and the idle/reset value is a clean all-zero word.
    always @(posedge clk_in) begin
        if (rst_in) begin
            enc_data_out  <= {(2*N){1'b0}};
            enc_valid_out <= 1'b0;
        end else if (enc_valid_in) begin
            enc_data_out  <= enc_comb;
            enc_valid_out <= 1'b1;
        end else begin
            enc_data_out  <= {(2*N){1'b0}};
            enc_valid_out <= 1'b0;
        end
    end

endmodule
