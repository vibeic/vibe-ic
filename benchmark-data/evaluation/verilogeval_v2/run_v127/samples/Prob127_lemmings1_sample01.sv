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

    // Moore outputs decode from state only.
    assign walk_left  = (state == LEFT);
    assign walk_right = (state == RIGHT);

    // bump_left (obstacle on the left) -> walk right;
    // bump_right (obstacle on the right) -> walk left;
    // both bumped -> still switch direction.
    always @(posedge clk or posedge areset) begin
        if (areset)
            state <= LEFT;                 // reset to walk left
        else begin
            case (state)
                LEFT:  state <= bump_left  ? RIGHT : LEFT;
                RIGHT: state <= bump_right ? LEFT  : RIGHT;
                default: state <= LEFT;
            endcase
        end
    end

endmodule
