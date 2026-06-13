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

  // Moore FSM for Lemmings4: walk, fall, dig, splatter.
  // Priority while WALKING: fall (ground=0) > dig > switch-direction (bump).
  localparam WL    = 3'd0; // walk left
  localparam WR    = 3'd1; // walk right
  localparam DL    = 3'd2; // digging, original direction left
  localparam DR    = 3'd3; // digging, original direction right
  localparam FL    = 3'd4; // falling, will resume walking left
  localparam FR    = 3'd5; // falling, will resume walking right
  localparam SPLAT = 3'd6; // splattered (all outputs 0, forever until reset)

  reg [2:0] state, next;
  reg [4:0] fcnt;          // counts fall cycles; during n-th fall cycle, fcnt==n

  wire in_fall      = (state == FL) || (state == FR);
  wire next_in_fall = (next  == FL) || (next  == FR);

  // "fell for MORE THAN 20 cycles" => fall_cycles > 20.
  // During the n-th fall cycle fcnt==n, so on the cycle ground returns
  // (still falling) the total fall duration is fcnt; splatter iff fcnt > 20.
  wire too_long = (fcnt > 5'd20);

  always @(*) begin
    case (state)
      WL: begin
        if      (!ground)   next = FL;        // fall has highest precedence
        else if (dig)       next = DL;        // dig next
        else if (bump_left) next = WR;        // bumped left -> walk right
        else                next = WL;
      end
      WR: begin
        if      (!ground)    next = FR;
        else if (dig)        next = DR;
        else if (bump_right) next = WL;       // bumped right -> walk left
        else                 next = WR;
      end
      // Digging continues until ground disappears, then falls.
      DL: next = ground ? DL : FL;
      DR: next = ground ? DR : FR;
      // Falling: stay until ground returns; on return splat if fell too long.
      FL: next = ground ? (too_long ? SPLAT : WL) : FL;
      FR: next = ground ? (too_long ? SPLAT : WR) : FR;
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
      // Counter keyed off the state being ENTERED, so during the n-th fall
      // cycle fcnt == n (1-indexed). Saturate to avoid wrap on long falls.
      if (next_in_fall) begin
        if (in_fall)
          fcnt <= (fcnt == 5'd31) ? 5'd31 : fcnt + 5'd1;  // continuing fall
        else
          fcnt <= 5'd1;                                    // entering fall
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
