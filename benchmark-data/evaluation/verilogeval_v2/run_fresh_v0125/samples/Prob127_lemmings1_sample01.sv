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

    always @(posedge clk or posedge areset) begin
        if (areset)
            state <= LEFT;
        else begin
            case (state)
                LEFT:  state <= bump_left  ? RIGHT : LEFT;
                RIGHT: state <= bump_right ? LEFT  : RIGHT;
                default: state <= LEFT;
            endcase
        end
    end

    assign walk_left  = (state == LEFT);
    assign walk_right = (state == RIGHT);

endmodule
