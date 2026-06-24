module TopModule (
  input clk,
  input areset,
  input bump_left,
  input bump_right,
  output walk_left,
  output walk_right
);

  localparam WL = 1'b0, WR = 1'b1;
  reg state;

  // bump_left (obstacle on the left) -> walk right; bump_right -> walk left.
  // When walking left, a left bump switches; when walking right, a right bump
  // switches. Either side asserted in the relevant state switches direction.
  always @(posedge clk or posedge areset) begin
    if (areset)
      state <= WL;
    else begin
      case (state)
        WL: state <= bump_left  ? WR : WL;
        WR: state <= bump_right ? WL : WR;
      endcase
    end
  end

  assign walk_left  = (state == WL);
  assign walk_right = (state == WR);

endmodule
