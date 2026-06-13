module TopModule (
  input a,
  input b,
  input c,
  input d,
  output reg out
);

  always @(*) begin
    out = (c & (a | ~b)) | (~c & a & ~d);
  end

endmodule
