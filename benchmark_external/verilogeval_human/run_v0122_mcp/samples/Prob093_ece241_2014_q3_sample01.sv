// K-map realized via an external 4-to-1 mux selected by {a,b}.
// mux_in[k] = K-map output for the ab column equal to k, as f(c,d):
//   ab=00 -> mux_in[0] = c | d
//   ab=01 -> mux_in[1] = 0
//   ab=10 -> mux_in[2] = c | ~d
//   ab=11 -> mux_in[3] = c & d
module TopModule (
  input c,
  input d,
  output [3:0] mux_in
);

  assign mux_in[0] = c | d;
  assign mux_in[1] = 1'b0;
  assign mux_in[2] = c | ~d;
  assign mux_in[3] = c & d;

endmodule
