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
    localparam WL = 3'd0,  // walk left
               WR = 3'd1,  // walk right
               FL = 3'd2,  // fall, was left
               FR = 3'd3,  // fall, was right
               DL = 3'd4,  // dig, was left
               DR = 3'd5;  // dig, was right

    reg [2:0] state, next;

    always @(*) begin
        case (state)
            WL: begin
                if (!ground)        next = FL;          // fall has highest precedence
                else if (dig)       next = DL;          // then dig
                else if (bump_left) next = WR;          // then switch
                else                next = WL;
            end
            WR: begin
                if (!ground)         next = FR;
                else if (dig)        next = DR;
                else if (bump_right) next = WL;
                else                 next = WR;
            end
            FL: next = ground ? WL : FL;                // land -> resume original dir
            FR: next = ground ? WR : FR;
            DL: next = ground ? DL : FL;                // dig until ground gone -> fall
            DR: next = ground ? DR : FR;
            default: next = WL;
        endcase
    end

    always @(posedge clk or posedge areset) begin
        if (areset)
            state <= WL;
        else
            state <= next;
    end

    assign walk_left  = (state == WL);
    assign walk_right = (state == WR);
    assign aaah       = (state == FL) || (state == FR);
    assign digging    = (state == DL) || (state == DR);
endmodule
