module TopModule (
  input  clk,
  input  areset,
  input  x,
  output z
);

  // Serial 2's complementer.
  // Copy input bits (LSB first) up to and including the first '1',
  // then invert all subsequent bits.
  // seen_one registers whether a '1' has already been encountered.
  reg seen_one;

  always @(posedge clk or posedge areset) begin
    if (areset)
      seen_one <= 1'b0;
    else if (x)
      seen_one <= 1'b1;
  end

  // Before/at the first '1': pass the bit through.
  // After the first '1': invert the bit.
  assign z = seen_one ? ~x : x;

endmodule
