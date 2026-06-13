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
    localparam FL = 2'd2;  // falling, was going left
    localparam FR = 2'd3;  // falling, was going right

    reg [1:0] state, next;

    always @(*) begin
        case (state)
            WL: begin
                if (!ground)      next = FL;
                else if (bump_left) next = WR;
                else              next = WL;
            end
            WR: begin
                if (!ground)       next = FR;
                else if (bump_right) next = WL;
                else               next = WR;
            end
            FL: next = ground ? WL : FL;
            FR: next = ground ? WR : FR;
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

endmodule
