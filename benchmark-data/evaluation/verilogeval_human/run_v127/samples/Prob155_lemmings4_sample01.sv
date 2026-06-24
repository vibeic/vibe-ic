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

  // Moore Lemmings FSM. Adds splatter: falling for MORE THAN 20 cycles then
  // hitting the ground splatters (all outputs 0 forever). 0-based fall counter
  // saturated at 20; decision at hit-ground is cnt >= 20 (i.e. fell >20 cycles).
  localparam WL    = 3'd0;
  localparam WR    = 3'd1;
  localparam FL    = 3'd2;  // falling, was going left
  localparam FR    = 3'd3;  // falling, was going right
  localparam DL    = 3'd4;  // digging, was going left
  localparam DR    = 3'd5;  // digging, was going right
  localparam SPLAT = 3'd6;  // splattered: all outputs 0 forever

  reg [2:0] state, next;
  reg [4:0] cnt;            // fall-duration counter (0..20, saturating)

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
      DL: next = ground ? DL : FL;
      DR: next = ground ? DR : FR;
      FL: begin
        if (ground) next = (cnt >= 5'd20) ? SPLAT : WL;  // splatter if fell >20
        else        next = FL;
      end
      FR: begin
        if (ground) next = (cnt >= 5'd20) ? SPLAT : WR;
        else        next = FR;
      end
      SPLAT: next = SPLAT;
      default: next = WL;
    endcase
  end

  always @(posedge clk or posedge areset) begin
    if (areset) begin
      state <= WL;
      cnt   <= 5'd0;
    end else begin
      state <= next;
      // Fall counter: 0 on entering a fall state, saturating increment while falling.
      if (next == FL || next == FR) begin
        if (state == FL || state == FR)
          cnt <= (cnt < 5'd20) ? (cnt + 5'd1) : 5'd20;
        else
          cnt <= 5'd0;
      end
    end
  end

  assign walk_left  = (state == WL);
  assign walk_right = (state == WR);
  assign aaah       = (state == FL) || (state == FR);
  assign digging    = (state == DL) || (state == DR);

endmodule
