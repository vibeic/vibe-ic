// Prob084_ece241_2013_q12 — 8-bit shift register + output mux.
// enable: shift, S into LSB. {A,B,C} (A MSB) addresses bit driven onto Z.
module TopModule (
  input clk,
  input enable,
  input S,
  input A,
  input B,
  input C,
  output reg Z
);

  reg [7:0] q;

  initial q = 8'd0;

  always @(posedge clk) begin
    if (enable)
      q <= {q[6:0], S};
  end

  always @(*)
    Z = q[{A, B, C}];

endmodule
