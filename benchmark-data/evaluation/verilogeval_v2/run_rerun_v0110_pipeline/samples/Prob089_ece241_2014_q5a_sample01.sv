module TopModule (
  input  clk,
  input  areset,
  input  x,
  output z
);
  // Serial 2's complementer, Moore: output is a function of state only and is
  // registered, so it is emitted one cycle after the bit that determines it.
  // 2's complement (LSB first) = copy bits up to & incl. the first 1, then invert.
  // Equivalent serial form: y = x ^ c ; c' = c | x  (c = "a 1 has been seen").
  reg c;       // seen-a-one flag (the state)
  reg z_reg;   // registered Moore output
  always @(posedge clk or posedge areset) begin
    if (areset) begin
      c     <= 1'b0;
      z_reg <= 1'b0;
    end else begin
      z_reg <= x ^ c;   // computed this cycle, presented next cycle (Moore)
      c     <= c | x;
    end
  end
  assign z = z_reg;
endmodule
