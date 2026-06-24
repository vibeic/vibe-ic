// program-SOLVED vector op (split into upper/lower halves); deterministic wiring.
module TopModule (
    input [15:0] in,
    output [7:0] out_hi,
    output [7:0] out_lo
);
    assign { out_hi, out_lo } = in;
endmodule
