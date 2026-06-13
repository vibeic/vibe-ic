module TopModule (
  input clk,
  input w,
  input R,
  input E,
  input L,
  output reg Q
);
    // One shift-register stage: load mux (L) feeds a shift-enable mux (E).
    // L has priority over E; when neither, hold.
    initial Q = 1'b0;             // deterministic power-up (no reset port)
    always @(posedge clk) begin
        if (L)
            Q <= R;        // load
        else if (E)
            Q <= w;        // shift in
        else
            Q <= Q;        // hold
    end
endmodule
