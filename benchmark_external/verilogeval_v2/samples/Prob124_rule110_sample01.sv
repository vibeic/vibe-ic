module TopModule (
  input          clk,
  input          load,
  input  [511:0] data,
  output [511:0] q
);
  reg  [511:0] state;
  wire [511:0] left  = {1'b0, state[511:1]};   // L = q[i+1], top boundary 0
  wire [511:0] center = state;                  // C = q[i]
  wire [511:0] right = {state[510:0], 1'b0};     // R = q[i-1], bottom boundary 0
  wire [511:0] nxt   = (~(left & center & right)) & (center | right);
  always @(posedge clk) begin
    if (load) state <= data;
    else      state <= nxt;
  end
  assign q = state;
endmodule
