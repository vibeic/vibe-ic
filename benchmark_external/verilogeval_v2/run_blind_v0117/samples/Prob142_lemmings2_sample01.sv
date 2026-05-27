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
    localparam WL = 2'd0;  // walking left
    localparam WR = 2'd1;  // walking right
    localparam FL = 2'd2;  // falling, was walking left
    localparam FR = 2'd3;  // falling, was walking right

    reg [1:0] state, next;

    always @(*) begin
        case (state)
            WL: begin
                if (!ground)        next = FL;          // fall has priority over bump
                else if (bump_left) next = WR;
                else                next = WL;
            end
            WR: begin
                if (!ground)         next = FR;
                else if (bump_right) next = WL;
                else                 next = WR;
            end
            FL: next = ground ? WL : FL;  // resume pre-fall direction
            FR: next = ground ? WR : FR;
            default: next = WL;
        endcase
    end

    always @(posedge clk or posedge areset) begin
        if (areset) state <= WL;
        else        state <= next;
    end

    // Moore outputs
    assign walk_left  = (state == WL);
    assign walk_right = (state == WR);
    assign aaah       = (state == FL) || (state == FR);
endmodule
