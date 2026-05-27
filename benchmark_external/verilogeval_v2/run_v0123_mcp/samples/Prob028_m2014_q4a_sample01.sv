module TopModule (
  input  d,
  input  ena,
  output reg q
);
  always_latch begin
    if (ena)
      q = d;
  end
endmodule
