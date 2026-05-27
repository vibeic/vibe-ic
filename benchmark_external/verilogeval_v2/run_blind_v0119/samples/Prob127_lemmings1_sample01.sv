module TopModule(
    input  clk,
    input  areset,
    input  bump_left,
    input  bump_right,
    output walk_left,
    output walk_right
);
    localparam WL = 1'b0; // walking left
    localparam WR = 1'b1; // walking right
    reg state, next;

    always @(*) begin
        case (state)
            WL: next = bump_left  ? WR : WL; // bumped on left -> walk right
            WR: next = bump_right ? WL : WR; // bumped on right -> walk left
            default: next = WL;
        endcase
    end

    always @(posedge clk or posedge areset) begin
        if (areset)            // asynchronous reset to walk_left
            state <= WL;
        else
            state <= next;
    end

    assign walk_left  = (state == WL);
    assign walk_right = (state == WR);
endmodule
