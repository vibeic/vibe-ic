module TopModule (
  input d,
  input ena,
  output logic q
);
  always_latch begin
    if (ena)
      q = d;
  end
endmodule
