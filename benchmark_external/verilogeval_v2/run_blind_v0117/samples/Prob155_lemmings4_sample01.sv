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
    localparam WL    = 3'd0;  // walk left
    localparam WR    = 3'd1;  // walk right
    localparam FL    = 3'd2;  // fall, was-left
    localparam FR    = 3'd3;  // fall, was-right
    localparam DL    = 3'd4;  // dig, was-left
    localparam DR    = 3'd5;  // dig, was-right
    localparam SPLAT = 3'd6;  // splattered (dead)

    reg [2:0]  state, next;
    reg [31:0] fall_cnt;     // cycles spent falling
    wire falling = (state == FL) || (state == FR);
    wire splat_now = falling && ground && (fall_cnt >= 32'd20);

    always @(*) begin
        case (state)
            WL: begin
                if      (!ground)   next = FL;
                else if (dig)       next = DL;
                else if (bump_left) next = WR;
                else                next = WL;
            end
            WR: begin
                if      (!ground)    next = FR;
                else if (dig)        next = DR;
                else if (bump_right) next = WL;
                else                 next = WR;
            end
            FL: next = ground ? (splat_now ? SPLAT : WL) : FL;
            FR: next = ground ? (splat_now ? SPLAT : WR) : FR;
            DL: next = ground ? DL : FL;
            DR: next = ground ? DR : FR;
            SPLAT: next = SPLAT;            // stays forever until reset
            default: next = WL;
        endcase
    end

    always @(posedge clk or posedge areset) begin
        if (areset) begin
            state    <= WL;
            fall_cnt <= 32'd0;
        end else begin
            state <= next;
            // fall_cnt tracks cycles already spent falling.
            // 0 when entering a fall (came from a non-fall state),
            // +1 for each additional cycle still falling.
            if (state == FL || state == FR) begin
                if (next == FL || next == FR) fall_cnt <= fall_cnt + 32'd1;
                // else: landing this cycle; splat_now read fall_cnt already
            end else if (next == FL || next == FR) begin
                fall_cnt <= 32'd0;  // first cycle of a new fall
            end
        end
    end

    // Moore outputs (all 0 in SPLAT)
    assign walk_left  = (state == WL);
    assign walk_right = (state == WR);
    assign aaah       = (state == FL) || (state == FR);
    assign digging    = (state == DL) || (state == DR);
endmodule
