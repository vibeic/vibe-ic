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

    reg state, next;

    always @(*) begin
        case (state)
            LEFT:  next = bump_left  ? RIGHT : LEFT;
            RIGHT: next = bump_right ? LEFT  : RIGHT;
            default: next = LEFT;
        endcase
    end

    always @(posedge clk or posedge areset) begin
        if (areset)
            state <= LEFT;
        else
            state <= next;
    end

    assign walk_left  = (state == LEFT);
    assign walk_right = (state == RIGHT);

endmodule
