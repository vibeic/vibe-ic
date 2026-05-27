module TopModule (
  input  clk,
  input  areset,
  input  bump_left,
  input  bump_right,
  input  ground,
  output walk_left,
  output walk_right,
  output aaah
);

  // Moore FSM. State holds walking direction and whether currently falling.
  localparam WL = 2'd0,   // walking left
             WR = 2'd1,   // walking right
             FL = 2'd2,   // falling, will resume walking left
             FR = 2'd3;   // falling, will resume walking right

  reg [1:0] state, next;

  always @(*) begin
    case (state)
      WL: if (!ground)      next = FL;            // ground gone: fall (priority)
          else if (bump_left) next = WR;          // bumped on left -> walk right
          else              next = WL;
      WR: if (!ground)      next = FR;
          else if (bump_right) next = WL;         // bumped on right -> walk left
          else              next = WR;
      FL: next = ground ? WL : FL;                // resume prior direction on landing
      FR: next = ground ? WR : FR;
      default: next = WL;
    endcase
  end

  always @(posedge clk or posedge areset) begin
    if (areset) state <= WL;
    else        state <= next;
  end

  assign walk_left  = (state == WL);
  assign walk_right = (state == WR);
  assign aaah       = (state == FL) || (state == FR);

endmodule
