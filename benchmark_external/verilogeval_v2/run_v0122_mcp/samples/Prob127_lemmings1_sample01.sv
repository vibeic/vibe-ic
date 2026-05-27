module TopModule (
    input  clk,
    input  areset,
    input  bump_left,
    input  bump_right,
    output walk_left,
    output walk_right
);

    localparam LEFT = 1'b0, RIGHT = 1'b1;
    reg state;

    reg nxt;
    always @(*) begin
        case (state)
            LEFT:  nxt = bump_left  ? RIGHT : LEFT;   // bumped on left -> walk right
            RIGHT: nxt = bump_right ? LEFT  : RIGHT;  // bumped on right -> walk left
            default: nxt = LEFT;
        endcase
    end

    always @(posedge clk or posedge areset) begin
        if (areset)
            state <= LEFT;
        else
            state <= nxt;
    end

    assign walk_left  = (state == LEFT);
    assign walk_right = (state == RIGHT);

endmodule
