module TopModule (
    input  clk,
    input  areset,
    input  bump_left,
    input  bump_right,
    input  ground,
    input  dig,
    output walk_left,
    output walk_right,
    output aaah,
    output digging
);
    localparam WL = 3'd0;  // walk left
    localparam WR = 3'd1;  // walk right
    localparam FL = 3'd2;  // fall, was going left
    localparam FR = 3'd3;  // fall, was going right
    localparam DL = 3'd4;  // dig, was going left
    localparam DR = 3'd5;  // dig, was going right

    reg [2:0] state, next;

    always @(*) begin
        case (state)
            WL: if (!ground)        next = FL;       // fall has highest precedence
                else if (dig)       next = DL;       // then dig
                else if (bump_left) next = WR;       // then switch direction
                else                next = WL;
            WR: if (!ground)         next = FR;
                else if (dig)        next = DR;
                else if (bump_right) next = WL;
                else                 next = WR;
            FL: next = ground ? WL : FL;             // land -> resume original dir
            FR: next = ground ? WR : FR;
            DL: next = ground ? DL : FL;             // dug through -> fall
            DR: next = ground ? DR : FR;
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
    assign digging    = (state == DL) || (state == DR);
endmodule
