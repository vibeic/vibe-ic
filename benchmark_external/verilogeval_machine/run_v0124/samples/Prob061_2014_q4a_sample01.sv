module TopModule (
  input clk,
  input w,
  input R,
  input E,
  input L,
  output reg Q
);

  // Synchronous register: rising-edge clk only, no reset in sensitivity list.
  // E is the enable: when E is low, Q holds its current state.
  // When enabled, L selects the source: L high -> Q<=R, L low -> Q<=w.
  initial Q = 1'b0;  // deterministic power-up (no reset port)

  always @(posedge clk) begin
    if (E) begin
      if (L)
        Q <= R;
      else
        Q <= w;
    end
    // E low: hold (no assignment)
  end

endmodule
