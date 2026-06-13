module TopModule (
  input clk,
  input w,
  input R,
  input E,
  input L,
  output reg Q = 1'b0
);
  always @(posedge clk) begin
    // L has priority: L high -> load R; else if E -> load w; else hold.
    if (L)
      Q <= R;
    else if (E)
      Q <= w;
    // L low and E low: hold (no assignment)
  end
endmodule
