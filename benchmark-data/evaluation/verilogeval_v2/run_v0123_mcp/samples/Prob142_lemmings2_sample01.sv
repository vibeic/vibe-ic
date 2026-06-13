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
    localparam WL = 2'd0, WR = 2'd1, FL = 2'd2, FR = 2'd3;
    reg [1:0] state, next;

    always @(*) begin
        case (state)
            WL: next = (!ground) ? FL : (bump_left ? WR : WL);
            WR: next = (!ground) ? FR : (bump_right ? WL : WR);
            FL: next = ground ? WL : FL;
            FR: next = ground ? WR : FR;
            default: next = WL;
        endcase
    end

    always @(posedge clk or posedge areset) begin
        if (areset) state <= WL;
        else        state <= next;
    end

    assign walk_left  = (state == WL);
    assign walk_right = (state == WR);
    assign aaah       = (state == FL) || (state == FR);
endmodule
