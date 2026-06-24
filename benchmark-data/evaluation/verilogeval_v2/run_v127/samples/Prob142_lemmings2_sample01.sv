module TopModule (
    input  clk,
    input  areset,
    input  bump_left,
    input  bump_right,
    input  ground,
    output walk_left,
    output walk_right,
    output aaah
);

    // Moore FSM. ground=0 (falling) has priority over bumps and preserves the
    // walking direction. bump_left -> walk_right, bump_right -> walk_left
    // (obstacle direction). Async reset to WALK_L.
    localparam WALK_L = 2'd0;
    localparam WALK_R = 2'd1;
    localparam FALL_L = 2'd2;   // falling, was walking left
    localparam FALL_R = 2'd3;   // falling, was walking right

    reg [1:0] state, next;

    always @(*) begin
        case (state)
            WALK_L: if (!ground)        next = FALL_L;
                    else if (bump_left) next = WALK_R;
                    else                next = WALK_L;
            WALK_R: if (!ground)         next = FALL_R;
                    else if (bump_right) next = WALK_L;
                    else                 next = WALK_R;
            FALL_L: next = ground ? WALK_L : FALL_L;
            FALL_R: next = ground ? WALK_R : FALL_R;
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

endmodule
