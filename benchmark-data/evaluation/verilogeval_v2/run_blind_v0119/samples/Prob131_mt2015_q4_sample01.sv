module TopModule(
    input  x,
    input  y,
    output z
);
    // Module A: z = (x^y) & x
    // Module B: from its waveform, z = ~(x^y)  (XNOR)
    wire a_out = (x ^ y) & x;   // A1 == A2
    wire b_out = ~(x ^ y);      // B1 == B2
    wire or_out  = a_out | b_out;   // A1 OR  B1
    wire and_out = a_out & b_out;   // A2 AND B2
    assign z = or_out ^ and_out;
endmodule
