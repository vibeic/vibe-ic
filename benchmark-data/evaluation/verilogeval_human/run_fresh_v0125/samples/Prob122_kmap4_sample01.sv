module TopModule (
  input a,
  input b,
  input c,
  input d,
  output reg out
);

  always @(*) begin
    out = a ^ b ^ c ^ d;
  end

endmodule
