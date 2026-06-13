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

  localparam WL = 3'd0,  // walk left
             WR = 3'd1,  // walk right
             FL = 3'd2,  // fall, resume left
             FR = 3'd3,  // fall, resume right
             DL = 3'd4,  // dig, originally left
             DR = 3'd5,  // dig, originally right
             SP = 3'd6;  // splattered (terminal)

  reg [2:0] state, next;
  reg [4:0] fcnt;          // cycles spent falling (saturating)
  // splatter if fell for more than 20 cycles before landing.
  // fcnt counts (falling cycles - 1) at the landing decision, so >=20 means >20 air cycles.
  wire splat = (fcnt >= 5'd20);

  always @(*) begin
    case (state)
      WL: if (!ground)        next = FL;
          else if (dig)       next = DL;
          else if (bump_left) next = WR;
          else                next = WL;
      WR: if (!ground)         next = FR;
          else if (dig)        next = DR;
          else if (bump_right) next = WL;
          else                 next = WR;
      FL: if (ground) next = splat ? SP : WL;
          else        next = FL;
      FR: if (ground) next = splat ? SP : WR;
          else        next = FR;
      DL: next = ground ? DL : FL;
      DR: next = ground ? DR : FR;
      SP: next = SP;                        // terminal until reset
      default: next = WL;
    endcase
  end

  always @(posedge clk or posedge areset) begin
    if (areset) begin
      state <= WL;
      fcnt  <= 5'd0;
    end else begin
      state <= next;
      // count cycles while falling; reset on any non-falling state
      if (state == FL || state == FR)
        fcnt <= (fcnt == 5'd31) ? fcnt : fcnt + 5'd1;
      else
        fcnt <= 5'd0;
    end
  end

  assign walk_left  = (state == WL);
  assign walk_right = (state == WR);
  assign aaah       = (state == FL) || (state == FR);
  assign digging    = (state == DL) || (state == DR);

endmodule
