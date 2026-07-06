module TopModule (
    input  clk,
    input  areset,
    input  bump_left,
    input  bump_right,
    output walk_left,
    output walk_right
);

    localparam LEFT  = 1'b0;
    localparam RIGHT = 1'b1;

    reg state, next_state;

    always @(*) begin
        if (bump_left && bump_right)
            next_state = ~state;          // bumped both sides: switch direction
        else if (bump_left)
            next_state = RIGHT;           // obstacle on the left: walk right
        else if (bump_right)
            next_state = LEFT;            // obstacle on the right: walk left
        else
            next_state = state;           // no bump: keep walking
    end

    always @(posedge clk or posedge areset) begin
        if (areset)
            state <= LEFT;
        else
            state <= next_state;
    end

    assign walk_left  = (state == LEFT);
    assign walk_right = (state == RIGHT);

endmodule
