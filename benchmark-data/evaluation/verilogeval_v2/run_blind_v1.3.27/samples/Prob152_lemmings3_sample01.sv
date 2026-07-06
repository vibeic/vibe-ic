module TopModule(
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
    localparam LEFT=3'd0, RIGHT=3'd1, FALL_L=3'd2, FALL_R=3'd3, DIG_L=3'd4, DIG_R=3'd5;

    reg [2:0] state, next;

    always @(*) begin
        case (state)
            LEFT:   next = !ground ? FALL_L : (dig ? DIG_L : (bump_left  ? RIGHT : LEFT));
            RIGHT:  next = !ground ? FALL_R : (dig ? DIG_R : (bump_right ? LEFT  : RIGHT));
            FALL_L: next = ground ? LEFT  : FALL_L;
            FALL_R: next = ground ? RIGHT : FALL_R;
            DIG_L:  next = !ground ? FALL_L : DIG_L;
            DIG_R:  next = !ground ? FALL_R : DIG_R;
            default: next = LEFT;
        endcase
    end

    always @(posedge clk or posedge areset) begin
        if (areset) state <= LEFT;
        else        state <= next;
    end

    assign walk_left  = (state == LEFT);
    assign walk_right = (state == RIGHT);
    assign aaah        = (state == FALL_L) || (state == FALL_R);
    assign digging     = (state == DIG_L) || (state == DIG_R);

endmodule
