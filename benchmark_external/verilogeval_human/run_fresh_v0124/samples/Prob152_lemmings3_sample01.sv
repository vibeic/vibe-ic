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

  // Moore FSM: walk/dig/fall, each with a remembered direction (L/R).
  localparam WL = 3'd0; // walk left
  localparam WR = 3'd1; // walk right
  localparam DL = 3'd2; // digging, was going left
  localparam DR = 3'd3; // digging, was going right
  localparam FL = 3'd4; // falling, was going left
  localparam FR = 3'd5; // falling, was going right

  reg [2:0] state, next;

  always @(*) begin
    case (state)
      WL: begin
        if      (!ground)   next = FL;        // fall (highest precedence)
        else if (dig)       next = DL;        // dig
        else if (bump_left) next = WR;        // switch
        else                next = WL;
      end
      WR: begin
        if      (!ground)    next = FR;
        else if (dig)        next = DR;
        else if (bump_right) next = WL;
        else                 next = WR;
      end
      DL: next = ground ? DL : FL;            // dig until no ground -> fall
      DR: next = ground ? DR : FR;
      FL: next = ground ? WL : FL;            // fall until ground -> resume dir
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
  assign digging    = (state == DL) || (state == DR);

endmodule
