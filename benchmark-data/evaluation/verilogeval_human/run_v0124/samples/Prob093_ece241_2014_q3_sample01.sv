module TopModule (
  input c,
  input d,
  output [3:0] mux_in
);
  // mux_in[k] = K-map column for ab=k, as a function of (c,d).
  // ab=00 -> mux_in[0]; ab=01 -> mux_in[1]; ab=10 -> mux_in[2]; ab=11 -> mux_in[3]
  assign mux_in[0] = c | d;     // col ab=00: 0 only when cd=00
  assign mux_in[1] = 1'b0;      // col ab=01: all zero
  assign mux_in[2] = c | ~d;    // col ab=10: 0 only when cd=01
  assign mux_in[3] = c & d;     // col ab=11: 1 only when cd=11
endmodule
