module TopModule (
    input  x,
    input  y,
    output z
);

    wire a_out, b_out;
    wire o_out, and_out;

    // Module A: z = (x^y) & x
    assign a_out = (x ^ y) & x;
    // Module B: z = ~(x^y)  (XNOR), derived from waveform
    assign b_out = ~(x ^ y);

    // First A OR first B
    assign o_out   = a_out | b_out;
    // Second A AND second B
    assign and_out = a_out & b_out;

    // OR output XOR AND output
    assign z = o_out ^ and_out;

endmodule
