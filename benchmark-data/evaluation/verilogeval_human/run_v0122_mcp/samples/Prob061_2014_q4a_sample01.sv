// One stage of a loadable shift register: flip-flop + two 2:1 muxes.
// Inner mux: E selects between hold (Q) and shift-in (w).
// Outer mux: L selects between R (load) and the inner-mux output.
// Q <= L ? R : (E ? w : Q). Registered on posedge clk. No reset.
module TopModule (
  input clk,
  input w,
  input R,
  input E,
  input L,
  output reg Q
);

  initial Q = 1'b0;

  always @(posedge clk)
    Q <= L ? R : (E ? w : Q);

endmodule
