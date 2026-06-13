module TopModule (
  input  clk,
  input  areset,
  input  x,
  output z
);
  // Serial 2's complement: starting from the LSB, copy bits up to and
  // including the first '1', then invert all subsequent bits.
  // Moore machine: the output z is a registered state output.
  // State carry: 0 = not yet seen a 1 (pass-through), 1 = seen a 1 (invert).
  reg seen_one;
  reg z_reg;
  assign z = z_reg;

  always @(posedge clk or posedge areset) begin
    if (areset) begin
      seen_one <= 1'b0;
      z_reg    <= 1'b0;
    end else begin
      if (!seen_one) begin
        z_reg    <= x;        // copy bits until (and including) the first 1
        seen_one <= x;        // once a 1 is seen, switch to invert mode
      end else begin
        z_reg <= ~x;          // invert all subsequent bits
      end
    end
  end
endmodule
