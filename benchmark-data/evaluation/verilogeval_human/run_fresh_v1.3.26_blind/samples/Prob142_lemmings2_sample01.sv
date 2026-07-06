module TopModule (
  input clk,
  input areset,
  input bump_left,
  input bump_right,
  input ground,
  output walk_left,
  output walk_right,
  output aaah
);

  localparam WL = 2'd0,  // walk left
             WR = 2'd1,  // walk right
             FL = 2'd2,  // falling, was walking left
             FR = 2'd3;  // falling, was walking right

  reg [1:0] state, next;

  always @(*) begin
    case (state)
      WL: next = (ground == 1'b0) ? FL : (bump_left  ? WR : WL);
      WR: next = (ground == 1'b0) ? FR : (bump_right ? WL : WR);
      FL: next = ground ? WL : FL;
      FR: next = ground ? WR : FR;
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

endmodule
