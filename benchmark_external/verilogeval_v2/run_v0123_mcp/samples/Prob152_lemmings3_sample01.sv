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
    localparam WL = 3'd0, WR = 3'd1, FL = 3'd2, FR = 3'd3, DL = 3'd4, DR = 3'd5;
    reg [2:0] state, next;

    always @(*) begin
        case (state)
            WL: begin
                if (!ground)    next = FL;
                else if (dig)   next = DL;
                else if (bump_left) next = WR;
                else            next = WL;
            end
            WR: begin
                if (!ground)    next = FR;
                else if (dig)   next = DR;
                else if (bump_right) next = WL;
                else            next = WR;
            end
            DL: next = ground ? DL : FL;  // dig until no ground -> fall
            DR: next = ground ? DR : FR;
            FL: next = ground ? WL : FL;  // resume original direction on landing
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
    assign digging    = (state == DL) || (state == DR);
endmodule
