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

  localparam WL    = 3'd0;
  localparam WR    = 3'd1;
  localparam FL    = 3'd2;
  localparam FR    = 3'd3;
  localparam DL    = 3'd4;
  localparam DR    = 3'd5;
  localparam SPLAT = 3'd6;

  reg [2:0] state, next;
  reg [5:0] fall_cnt;   // number of cycles (incl. current) spent in current fall

  wire falling = (state == FL) || (state == FR);
  // fall_cnt counts the current falling cycle as well; "more than 20 cycles"
  // means the lemming has been in a fall state for >20 cycles -> fall_cnt > 20
  wire splat_now = (fall_cnt > 6'd20);

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
      FL: begin
        if (ground)
          next = splat_now ? SPLAT : WL;
        else
          next = FL;
      end
      FR: begin
        if (ground)
          next = splat_now ? SPLAT : WR;
        else
          next = FR;
      end
      DL:   next = ground ? DL : FL;
      DR:   next = ground ? DR : FR;
      SPLAT: next = SPLAT;
      default: next = WL;
    endcase
  end

  always @(posedge clk or posedge areset) begin
    if (areset) begin
      state    <= WL;
      fall_cnt <= 6'd0;
    end else begin
      state <= next;
      // fall_cnt reflects how many cycles we will have been falling in the
      // NEXT state: 1 on the first fall cycle, incrementing each cycle.
      if (next == FL || next == FR) begin
        if (falling)
          fall_cnt <= (fall_cnt == 6'd63) ? 6'd63 : fall_cnt + 6'd1;
        else
          fall_cnt <= 6'd1;   // entering a fall: first falling cycle
      end else begin
        fall_cnt <= 6'd0;
      end
    end
  end

  assign walk_left  = (state == WL);
  assign walk_right = (state == WR);
  assign aaah       = (state == FL) || (state == FR);
  assign digging    = (state == DL) || (state == DR);

endmodule
