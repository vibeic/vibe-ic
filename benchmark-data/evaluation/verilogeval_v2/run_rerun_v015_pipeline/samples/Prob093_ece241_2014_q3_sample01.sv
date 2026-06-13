module TopModule (
  input        c,
  input        d,
  output [3:0] mux_in
);
  // 4-to-1 mux selected by {a,b}: mux_in[{a,b}] chosen.
  // K-map columns (ab) as functions of (c,d):
  //   ab=00 -> mux_in[0] : 1 except cd=00  -> c | d
  //   ab=01 -> mux_in[1] : all 0           -> 0
  //   ab=10 -> mux_in[2] : 0 only at c=0,d=1 -> c | ~d
  //   ab=11 -> mux_in[3] : 1 only at cd=11  -> c & d
  assign mux_in[0] = c | d;
  assign mux_in[1] = 1'b0;
  assign mux_in[2] = c | ~d;
  assign mux_in[3] = c & d;
endmodule
