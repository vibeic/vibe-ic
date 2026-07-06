module TopModule (
  input clk,
  input areset,
  input bump_left,
  input bump_right,
  input ground,
  input dig,
  output walk_left,
  output walk_right,
  output aaah,
  output digging
);

  localparam WL=0, WR=1, FALL_L=2, FALL_R=3, DIG_L=4, DIG_R=5;
  reg [2:0] state, next;

  always @(*) begin
    case (state)
      WL:      next = !ground ? FALL_L : dig ? DIG_L : bump_left  ? WR : WL;
      WR:      next = !ground ? FALL_R : dig ? DIG_R : bump_right ? WL : WR;
      DIG_L:   next = !ground ? FALL_L : DIG_L;
      DIG_R:   next = !ground ? FALL_R : DIG_R;
      FALL_L:  next =  ground ? WL     : FALL_L;
      FALL_R:  next =  ground ? WR     : FALL_R;
      default: next = WL;
    endcase
  end

  always @(posedge clk or posedge areset) begin
    if (areset) state <= WL;
    else        state <= next;
  end

  assign walk_left  = (state == WL);
  assign walk_right = (state == WR);
  assign aaah       = (state == FALL_L) || (state == FALL_R);
  assign digging    = (state == DIG_L)  || (state == DIG_R);

endmodule
