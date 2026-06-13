module TopModule (
  input clk,
  input resetn,
  input in,
  output out
);
  reg [3:0] sr = 4'b0;

  always @(posedge clk) begin
    if (!resetn)
      sr <= 4'b0;
    else
      sr <= {sr[2:0], in};   // shift left, load in into LSB
  end

  assign out = sr[3];        // MSB
endmodule
