// 8x1 memory: 8-bit shift register + 8-to-1 read mux.
// enable is synchronous active-high; shift Q[0]<=S, Q[i]<=Q[i-1].
// Z reads the bit addressed by {A,B,C} (000 -> Q[0] ... 111 -> Q[7]).
module TopModule (
  input clk,
  input enable,
  input S,
  input A,
  input B,
  input C,
  output reg Z
);

  reg [7:0] Q;

  always @(posedge clk) begin
    if (enable)
      Q <= {Q[6:0], S};
  end

  always @(*)
    Z = Q[{A, B, C}];

endmodule
