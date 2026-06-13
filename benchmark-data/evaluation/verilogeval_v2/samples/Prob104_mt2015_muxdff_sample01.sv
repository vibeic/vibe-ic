module TopModule (
  input  clk,
  input  L,
  input  q_in,
  input  r_in,
  output reg Q
);
  // Single-bit slice: 2:1 mux (select between r_in when L, else q_in) into a DFF.
  always @(posedge clk) begin
    if (L)
      Q <= r_in;
    else
      Q <= q_in;
  end
endmodule
