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
    localparam WL    = 3'd0;   // walking left
    localparam WR    = 3'd1;   // walking right
    localparam FL    = 3'd2;   // falling, was left
    localparam FR    = 3'd3;   // falling, was right
    localparam DL    = 3'd4;   // digging, was left
    localparam DR    = 3'd5;   // digging, was right
    localparam SPLAT = 3'd6;   // splattered (terminal)

    reg [2:0] state, next;
    reg [31:0] fall_cnt;       // counts cycles spent falling

    wire falling     = (state == FL) || (state == FR);
    wire splat_now   = falling && ground && (fall_cnt > 32'd20);  // fell >20 then lands

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
            FL: next = ground ? (fall_cnt > 32'd20 ? SPLAT : WL) : FL;
            FR: next = ground ? (fall_cnt > 32'd20 ? SPLAT : WR) : FR;
            DL: next = ground ? DL : FL;
            DR: next = ground ? DR : FR;
            SPLAT: next = SPLAT;       // terminal until reset
            default: next = WL;
        endcase
    end

    always @(posedge clk or posedge areset) begin
        if (areset) begin
            state    <= WL;
            fall_cnt <= 32'd0;
        end else begin
            state <= next;
            // count falling cycles; reset count when not falling
            if (next == FL || next == FR)
                fall_cnt <= fall_cnt + 32'd1;
            else
                fall_cnt <= 32'd0;
        end
    end

    assign walk_left  = (state == WL);
    assign walk_right = (state == WR);
    assign aaah       = (state == FL) || (state == FR);
    assign digging    = (state == DL) || (state == DR);
endmodule
