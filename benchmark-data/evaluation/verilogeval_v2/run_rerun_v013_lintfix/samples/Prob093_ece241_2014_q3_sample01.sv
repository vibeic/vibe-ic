module TopModule (
  input        c,
  input        d,
  output [3:0] mux_in
);

  // 4-to-1 mux selected by {a,b}: mux_in[{a,b}].
  // From the K-map, each mux_in[i] is a function of c and d:
  //   mux_in[0] (ab=00): 1 unless cd=00          -> c | d
  //   mux_in[1] (ab=01): always 0                -> 0
  //   mux_in[2] (ab=10): 1 unless cd=01 (c=0,d=1)-> c | ~d
  //   mux_in[3] (ab=11): 1 only when cd=11       -> c & d
  assign mux_in[0] = c | d;
  assign mux_in[1] = 1'b0;
  assign mux_in[2] = c | ~d;
  assign mux_in[3] = c & d;

endmodule
