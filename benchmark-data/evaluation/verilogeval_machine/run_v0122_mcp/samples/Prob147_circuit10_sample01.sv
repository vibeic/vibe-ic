// Prob147_circuit10 — registered majority c; q=a^b^c; state=c.
module TopModule (
  input clk,
  input a,
  input b,
  output q,
  output state
);

  reg c;
  initial c = 1'b0;   // reset-less registered node power-up (separate block)

  always @(posedge clk)
    c <= (a & b) | (a & c) | (b & c);

  assign q     = a ^ b ^ c;
  assign state = c;

endmodule
