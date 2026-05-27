// Prob028_m2014_q4a — transparent D latch.
// ena high: q = d; ena low: q holds. Intended latch (no else branch).
module TopModule (
  input d,
  input ena,
  output logic q
);

  always_latch
    if (ena)
      q = d;

endmodule
