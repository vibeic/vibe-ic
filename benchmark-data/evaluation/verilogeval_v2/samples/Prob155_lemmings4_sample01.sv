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

  localparam WL=0, WR=1, FL=2, FR=3, DL=4, DR=5, SPLAT=6;
  reg [2:0] state, next;
  reg [4:0] fcnt;          // number of cycles spent falling (saturating)

  wire falling = (state == FL) || (state == FR);
  wire too_long = (fcnt > 5'd20);

  always @(*) begin
    case (state)
      WL: begin
        if      (!ground)    next = FL;
        else if (dig)        next = DL;
        else if (bump_left)  next = WR;
        else                 next = WL;
      end
      WR: begin
        if      (!ground)    next = FR;
        else if (dig)        next = DR;
        else if (bump_right) next = WL;
        else                 next = WR;
      end
      FL: next = ground ? (too_long ? SPLAT : WL) : FL;
      FR: next = ground ? (too_long ? SPLAT : WR) : FR;
      DL: next = ground ? DL : FL;
      DR: next = ground ? DR : FR;
      SPLAT: next = SPLAT;
      default: next = WL;
    endcase
  end

  always @(posedge clk or posedge areset) begin
    if (areset) begin
      state <= WL;
      fcnt  <= 5'd0;
    end else begin
      state <= next;
      // count falling cycles: 1 on entering a fall, then increment (saturate)
      if (next == FL || next == FR) begin
        if (falling)
          fcnt <= (fcnt < 5'd31) ? fcnt + 5'd1 : fcnt;
        else
          fcnt <= 5'd1;   // first cycle of this fall
      end else begin
        fcnt <= 5'd0;
      end
    end
  end

  assign walk_left  = (state == WL);
  assign walk_right = (state == WR);
  assign aaah       = (state == FL) || (state == FR);
  assign digging    = (state == DL) || (state == DR);

endmodule
