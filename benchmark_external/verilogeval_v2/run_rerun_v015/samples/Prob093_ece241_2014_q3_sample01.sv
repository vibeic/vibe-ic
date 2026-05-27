module TopModule (
  input        c,
  input        d,
  output [3:0] mux_in
);

  // 4-to-1 mux selected by {a,b}: mux_in[0]=ab00, mux_in[1]=ab01,
  // mux_in[3]=ab11, mux_in[2]=ab10.  Each entry is f(c,d) from the K-map.
  //   ab=00 column (cd 00,01,11,10 -> 0,1,1,1) = c | d
  //   ab=01 column = 0
  //   ab=11 column (-> 0,0,1,0)               = c & d
  //   ab=10 column (-> 1,0,1,1)               = c | ~d
  assign mux_in[0] = c | d;
  assign mux_in[1] = 1'b0;
  assign mux_in[2] = c | ~d;
  assign mux_in[3] = c & d;

endmodule
