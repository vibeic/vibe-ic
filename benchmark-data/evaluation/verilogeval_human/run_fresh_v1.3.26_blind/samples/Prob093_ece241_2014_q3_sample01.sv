module TopModule (
  input c,
  input d,
  output [3:0] mux_in
);

  // The external 4-to-1 mux selects with {a,b}:
  //   ab=00 -> mux_in[0], ab=01 -> mux_in[1],
  //   ab=10 -> mux_in[2], ab=11 -> mux_in[3].
  // Each mux_in bit is the K-map column (as a function of c,d).
  //   ab=00 column vs cd(00,01,11,10) = 0,1,1,1  -> c | d
  //   ab=01 column                    = 0,0,0,0  -> 0
  //   ab=10 column                    = 1,0,1,1  -> c | ~d
  //   ab=11 column                    = 0,0,1,0  -> c & d
  assign mux_in[0] = c | d;
  assign mux_in[1] = 1'b0;
  assign mux_in[2] = c | ~d;
  assign mux_in[3] = c & d;

endmodule
