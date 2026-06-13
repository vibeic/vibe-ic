module TopModule (
    input  clk,
    input  areset,
    input  bump_left,
    input  bump_right,
    output walk_left,
    output walk_right
);

    localparam WALK_LEFT  = 1'b0;
    localparam WALK_RIGHT = 1'b1;

    reg state, next;

    always @(*) begin
        case (state)
            WALK_LEFT:  next = bump_left  ? WALK_RIGHT : WALK_LEFT;
            WALK_RIGHT: next = bump_right ? WALK_LEFT  : WALK_RIGHT;
            default:    next = WALK_LEFT;
        endcase
    end

    always @(posedge clk or posedge areset) begin
        if (areset)
            state <= WALK_LEFT;
        else
            state <= next;
    end

    assign walk_left  = (state == WALK_LEFT);
    assign walk_right = (state == WALK_RIGHT);

endmodule
