module TopModule (
  input a,
  input b,
  input c,
  input d,
  output reg out
);

  // K-map with don't-cares; minimal cover (d input unused): out = a | (~b & c)
  always @(*) begin
    out = a | (~b & c);
  end

endmodule
