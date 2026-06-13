module TopModule (
  input clk,
  input areset,
  input bump_left,
  input bump_right,
  output walk_left,
  output walk_right
);

  localparam WL = 1'b0, WR = 1'b1;
  reg state, next;

  always @(*) begin
    case (state)
      WL: next = bump_left  ? WR : WL;
      WR: next = bump_right ? WL : WR;
      default: next = WL;
    endcase
  end

  always @(posedge clk or posedge areset) begin
    if (areset)
      state <= WL;
    else
      state <= next;
  end

  assign walk_left  = (state == WL);
  assign walk_right = (state == WR);

endmodule
