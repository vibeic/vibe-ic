// program-SOLVED vector op (bit reverse); deterministic wiring.
module TopModule (
    input [7:0] in,
    output reg [7:0] out
);
    integer i;
    always @(*)
        for (i = 0; i < 8; i = i + 1)
            out[i] = in[7 - i];
endmodule
