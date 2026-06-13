// Transparent D-latch with enable.
// ena high -> q follows d; ena low -> q holds (latch).
module TopModule (
  input d,
  input ena,
  output reg q
);

  always @(*)
    if (ena)
      q = d;

endmodule
