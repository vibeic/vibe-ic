module TopModule (
  input c,
  input d,
  output [3:0] mux_in
);

  // mux_in[k] is the K-map column selected when {a,b}=k.
  // Column ab=00 (mux_in[0]): 1 except cd=00            -> c | d
  // Column ab=01 (mux_in[1]): all 0                      -> 0
  // Column ab=11 (mux_in[3]): 1 only at cd=11            -> c & d
  // Column ab=10 (mux_in[2]): 0 only at cd=01            -> c | ~d
  assign mux_in[0] = c | d;
  assign mux_in[1] = 1'b0;
  assign mux_in[2] = c | ~d;
  assign mux_in[3] = c & d;

endmodule
