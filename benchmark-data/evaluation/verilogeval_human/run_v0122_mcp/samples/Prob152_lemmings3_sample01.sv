module TopModule (
  input  clk,
  input  areset,
  input  bump_left,
  input  bump_right,
  input  ground,
  input  dig,
  output walk_left,
  output walk_right,
  output aaah,
  output digging
);

  // Moore FSM. Direction-tagged states for walk/fall/dig.
  localparam WL = 3'd0,  // walk left
             WR = 3'd1,  // walk right
             FL = 3'd2,  // fall, resume left
             FR = 3'd3,  // fall, resume right
             DL = 3'd4,  // dig, originally left
             DR = 3'd5;  // dig, originally right

  reg [2:0] state, next;

  always @(*) begin
    case (state)
      // Walking: precedence fall > dig > switch
      WL: if (!ground)        next = FL;
          else if (dig)       next = DL;
          else if (bump_left) next = WR;
          else                next = WL;
      WR: if (!ground)         next = FR;
          else if (dig)        next = DR;
          else if (bump_right) next = WL;
          else                 next = WR;
      // Falling: resume prior direction once ground returns
      FL: next = ground ? WL : FL;
      FR: next = ground ? WR : FR;
      // Digging: dig through until ground disappears, then fall (same direction)
      DL: next = ground ? DL : FL;
      DR: next = ground ? DR : FR;
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
  assign digging    = (state == DL) || (state == DR);

endmodule
