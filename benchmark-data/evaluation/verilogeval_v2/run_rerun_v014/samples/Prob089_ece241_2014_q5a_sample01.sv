module TopModule (
  input  clk,
  input  areset,
  input  x,
  output z
);

  // Serial 2's complementer, processing from LSB first.
  // Rule: copy input bits up to and including the first '1', then invert
  // all higher bits. Equivalently z = x XOR (a '1' was seen in a lower bit).
  // 'seen' is the registered state; while reset is asserted the conversion
  // is held (state cleared) and resumes (begins) when reset is released.
  reg seen;

  always @(posedge clk or posedge areset) begin
    if (areset)
      seen <= 1'b0;
    else
      seen <= seen | x;
  end

  assign z = x ^ seen;

endmodule
