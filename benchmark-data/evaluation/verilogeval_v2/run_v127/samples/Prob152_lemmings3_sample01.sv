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

    // Moore FSM. A walking Lemming can fall, dig, or switch direction, with
    // precedence fall > dig > switch. Falling/digging ignore bumps and dig.
    // Async reset to WALK_L. Direction is preserved through fall and dig.
    localparam WALK_L=3'd0, WALK_R=3'd1, FALL_L=3'd2, FALL_R=3'd3,
               DIG_L =3'd4, DIG_R =3'd5;

    reg [2:0] state, next;

    always @(*) begin
        case (state)
            WALK_L: if (!ground)        next = FALL_L;
                    else if (dig)       next = DIG_L;
                    else if (bump_left) next = WALK_R;
                    else                next = WALK_L;
            WALK_R: if (!ground)         next = FALL_R;
                    else if (dig)        next = DIG_R;
                    else if (bump_right) next = WALK_L;
                    else                 next = WALK_R;
            FALL_L: next = ground ? WALK_L : FALL_L;
            FALL_R: next = ground ? WALK_R : FALL_R;
            DIG_L:  next = ground ? DIG_L : FALL_L;   // dig until no ground -> fall
            DIG_R:  next = ground ? DIG_R : FALL_R;
            default: next = WALK_L;
        endcase
    end

    always @(posedge clk or posedge areset) begin
        if (areset) state <= WALK_L;
        else        state <= next;
    end

    assign walk_left  = (state == WALK_L);
    assign walk_right = (state == WALK_R);
    assign aaah       = (state == FALL_L) || (state == FALL_R);
    assign digging    = (state == DIG_L)  || (state == DIG_R);

endmodule
