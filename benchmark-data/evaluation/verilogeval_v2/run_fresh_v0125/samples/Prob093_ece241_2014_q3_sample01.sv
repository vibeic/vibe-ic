module TopModule (
  input        c,
  input        d,
  output [3:0] mux_in
);

  // 4-to-1 mux selected by {a,b}: mux_in[0]=ab00, [1]=ab01, [3]=ab11, [2]=ab10.
  // Each column reduced over c,d from the K-map.
  assign mux_in[0] = c | d;    // ab=00 column
  assign mux_in[1] = 1'b0;     // ab=01 column (all zero)
  assign mux_in[2] = c | ~d;   // ab=10 column
  assign mux_in[3] = c & d;    // ab=11 column

endmodule
