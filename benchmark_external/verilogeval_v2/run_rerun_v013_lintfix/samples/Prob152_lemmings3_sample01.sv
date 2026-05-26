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

  localparam WL = 3'd0;
  localparam WR = 3'd1;
  localparam FL = 3'd2;
  localparam FR = 3'd3;
  localparam DL = 3'd4;
  localparam DR = 3'd5;

  reg [2:0] state, next;

  always @(*) begin
    case (state)
      WL: begin
        if (!ground)        next = FL;
        else if (dig)       next = DL;
        else if (bump_left) next = WR;
        else                next = WL;
      end
      WR: begin
        if (!ground)         next = FR;
        else if (dig)        next = DR;
        else if (bump_right) next = WL;
        else                 next = WR;
      end
      FL: next = ground ? WL : FL;
      FR: next = ground ? WR : FR;
      DL: next = ground ? DL : FL;
      DR: next = ground ? DR : FR;
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
  assign aaah       = (state == FL) || (state == FR);
  assign digging    = (state == DL) || (state == DR);

endmodule
