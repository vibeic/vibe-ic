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
    localparam WL = 2'd0; // walk left
    localparam WR = 2'd1; // walk right
    localparam FL = 2'd2; // fall, was going left
    localparam FR = 2'd3; // fall, was going right

    reg [1:0] state, next;

    always @(*) begin
        case (state)
            WL: if (!ground)        next = FL;
                else if (bump_left) next = WR;
                else                next = WL;
            WR: if (!ground)         next = FR;
                else if (bump_right) next = WL;
                else                 next = WR;
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
