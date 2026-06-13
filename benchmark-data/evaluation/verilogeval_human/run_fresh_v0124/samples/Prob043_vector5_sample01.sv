module TopModule (
  input a,
  input b,
  input c,
  input d,
  input e,
  output [24:0] out
);

  // Each output bit is the XNOR (equality) of a pair of the 5 inputs.
  // Ordering per spec: row index runs a..e (MSB-first), column index runs a..e.
  // out[24]=~(a^a), out[23]=~(a^b), ... out[0]=~(e^e).
  wire [4:0] v = {a, b, c, d, e};
  genvar i, j;
  generate
    for (i = 0; i < 5; i = i + 1) begin : row
      for (j = 0; j < 5; j = j + 1) begin : col
        assign out[24 - (i*5 + j)] = ~(v[4 - i] ^ v[4 - j]);
      end
    end
  endgenerate

endmodule
