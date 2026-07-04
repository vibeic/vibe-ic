module reed_solomon_encoder #(
    parameter DATA_WIDTH = 8,   // Width of input data symbols
    parameter N = 255,          // Total number of symbols in the codeword
    parameter K = 223           // Number of data symbols
) (
    input wire clk,
    input wire reset,
    input wire enable,
    input wire [DATA_WIDTH-1:0] data_in,
    input wire valid_in,
    output reg [DATA_WIDTH-1:0] codeword_out,
    output reg valid_out,
    output reg [DATA_WIDTH-1:0] parity_0,
    output reg [DATA_WIDTH-1:0] parity_1
);

    localparam PARITY_SYMBOLS = N - K;  // Number of parity symbols

    // Internal feedback term for the shift-register based encoder
    reg [DATA_WIDTH-1:0] feedback;

    always @(posedge clk or posedge reset) begin
        if (reset) begin
            // Reset all registers
            parity_0     <= 0;
            parity_1     <= 0;
            codeword_out <= 0;
            valid_out    <= 0;
        end else if (enable && valid_in) begin
            // feedback = data_in XOR previous parity_1
            feedback     = data_in ^ parity_1;
            // new parity_1 = previous parity_0 XOR (feedback * generator coeff)
            parity_1     <= parity_0 ^ (feedback * generator_polynomial(1));
            // new parity_0 = feedback
            parity_0     <= feedback;
            // codeword output is the current data symbol
            codeword_out <= data_in;
            valid_out    <= valid_in & enable;
        end
    end

    // Choose between 8'h1D and 8'h33 based on the coefficient index
    function [DATA_WIDTH-1:0] generator_polynomial(input integer index);
        begin
            generator_polynomial = (index == 0) ? 8'h1D : 8'h33;
        end
    endfunction

endmodule
