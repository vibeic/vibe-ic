module TopModule (
  input c,
  input d,
  output [3:0] mux_in
);
    // 4:1 mux selected by {a,b} with index = 2a+b.
    // Each mux_in[k] is the K-map output as a function of c,d for that ab column.
    assign mux_in[0] = c | d;    // ab=00: 1 except cd=00
    assign mux_in[1] = 1'b0;     // ab=01: all 0
    assign mux_in[2] = c | ~d;   // ab=10: 1 except cd=01
    assign mux_in[3] = c & d;    // ab=11: 1 only at cd=11
endmodule
