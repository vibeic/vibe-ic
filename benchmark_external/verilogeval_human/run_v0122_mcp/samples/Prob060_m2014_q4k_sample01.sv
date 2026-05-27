// 4-stage shift register, posedge clk, active-low SYNCHRONOUS reset.
// resetn=0 -> all stages clear; else shift 'in' through 4 flops to out.
module TopModule (
  input clk,
  input resetn,
  input in,
  output out
);

  reg [3:0] sr;

  always @(posedge clk) begin
    if (!resetn)
      sr <= 4'b0;
    else
      sr <= {sr[2:0], in};
  end

  assign out = sr[3];

endmodule
