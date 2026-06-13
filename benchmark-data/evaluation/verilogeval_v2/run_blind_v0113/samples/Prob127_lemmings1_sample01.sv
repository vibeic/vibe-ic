module TopModule (
    input  clk,
    input  areset,
    input  bump_left,
    input  bump_right,
    output walk_left,
    output walk_right
);
    localparam WL = 1'b0;  // walking left
    localparam WR = 1'b1;  // walking right
    reg state;

    always @(posedge clk or posedge areset) begin
        if (areset)
            state <= WL;
        else begin
            case (state)
                WL: state <= bump_left  ? WR : WL;
                WR: state <= bump_right ? WL : WR;
                default: state <= WL;
            endcase
        end
    end

    // Moore outputs: function of state only
    assign walk_left  = (state == WL);
    assign walk_right = (state == WR);
endmodule
