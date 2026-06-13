module TopModule (
  input        c,
  input        d,
  output [3:0] mux_in
);
  // 4:1 mux selected by {a,b}: ab=00->mux_in[0], 01->mux_in[1], 11->mux_in[3], 10->mux_in[2].
  // For each ab column read the K-map as a function of c,d:
  //   ab=00 column: 1 except cd=00 -> c | d
  assign mux_in[0] = c | d;
  //   ab=01 column: all zero
  assign mux_in[1] = 1'b0;
  //   ab=10 column: 1 except cd=01 -> c | ~d
  assign mux_in[2] = c | ~d;
  //   ab=11 column: only cd=11 -> c & d
  assign mux_in[3] = c & d;
endmodule
