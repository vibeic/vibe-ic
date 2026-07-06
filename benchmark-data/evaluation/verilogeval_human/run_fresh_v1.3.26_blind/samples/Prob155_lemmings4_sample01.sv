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

  localparam WL=0, WR=1, FALL_L=2, FALL_R=3, DIG_L=4, DIG_R=5, SPLAT=6;
  reg [2:0] state, next;

  // Count clock cycles spent falling.  Increment on the current state being a
  // fall state (so at the ground-hit cycle, count == (cycles fallen - 1)).
  // "Fell for more than 20 cycles" therefore splatters when count >= 20.
  reg [5:0] fall_cnt;

  always @(*) begin
    case (state)
      WL:      next = !ground ? FALL_L : dig ? DIG_L : bump_left  ? WR : WL;
      WR:      next = !ground ? FALL_R : dig ? DIG_R : bump_right ? WL : WR;
      DIG_L:   next = !ground ? FALL_L : DIG_L;
      DIG_R:   next = !ground ? FALL_R : DIG_R;
      FALL_L:  next =  ground ? ((fall_cnt >= 20) ? SPLAT : WL) : FALL_L;
      FALL_R:  next =  ground ? ((fall_cnt >= 20) ? SPLAT : WR) : FALL_R;
      SPLAT:   next = SPLAT;
      default: next = WL;
    endcase
  end

  always @(posedge clk or posedge areset) begin
    if (areset) begin
      state    <= WL;
      fall_cnt <= 0;
    end else begin
      state <= next;
      if (state == FALL_L || state == FALL_R)
        fall_cnt <= (fall_cnt >= 6'd40) ? fall_cnt : fall_cnt + 1'b1;
      else
        fall_cnt <= 0;
    end
  end

  assign walk_left  = (state == WL);
  assign walk_right = (state == WR);
  assign aaah       = (state == FALL_L) || (state == FALL_R);
  assign digging    = (state == DIG_L)  || (state == DIG_R);

endmodule
