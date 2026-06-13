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

    localparam WL    = 3'd0;  // walking left
    localparam WR    = 3'd1;  // walking right
    localparam FL    = 3'd2;  // falling, was going left
    localparam FR    = 3'd3;  // falling, was going right
    localparam DL    = 3'd4;  // digging, was going left
    localparam DR    = 3'd5;  // digging, was going right
    localparam SPLAT = 3'd6;  // splattered

    reg [2:0] state, next;

    // count of falling cycles; saturating
    reg [4:0] fall_cnt;

    wire falling = (state == FL) || (state == FR);
    wire too_long = (fall_cnt >= 5'd20);  // fell more than 20 cycles

    always @(*) begin
        case (state)
            WL: begin
                if (!ground)        next = FL;
                else if (dig)       next = DL;
                else if (bump_left) next = WR;
                else                next = WL;
            end
            WR: begin
                if (!ground)         next = FR;
                else if (dig)        next = DR;
                else if (bump_right) next = WL;
                else                 next = WR;
            end
            FL: begin
                if (ground) next = too_long ? SPLAT : WL;
                else        next = FL;
            end
            FR: begin
                if (ground) next = too_long ? SPLAT : WR;
                else        next = FR;
            end
            DL: next = ground ? DL : FL;
            DR: next = ground ? DR : FR;
            SPLAT: next = SPLAT;
            default: next = WL;
        endcase
    end

    always @(posedge clk or posedge areset) begin
        if (areset) begin
            state    <= WL;
            fall_cnt <= 5'd0;
        end else begin
            state <= next;
            // count falling cycles; reset when not falling
            if (next == FL || next == FR) begin
                if (falling)
                    fall_cnt <= (fall_cnt == 5'd31) ? 5'd31 : fall_cnt + 5'd1;
                else
                    fall_cnt <= 5'd0;  // just started to fall
            end else begin
                fall_cnt <= 5'd0;
            end
        end
    end

    assign walk_left  = (state == WL);
    assign walk_right = (state == WR);
    assign aaah       = (state == FL) || (state == FR);
    assign digging    = (state == DL) || (state == DR);

endmodule
