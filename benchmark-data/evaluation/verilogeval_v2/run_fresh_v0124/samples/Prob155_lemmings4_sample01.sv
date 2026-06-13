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
    localparam WL    = 3'd0; // walking left
    localparam WR    = 3'd1; // walking right
    localparam FL    = 3'd2; // falling, will resume left
    localparam FR    = 3'd3; // falling, will resume right
    localparam DL    = 3'd4; // digging, will resume left
    localparam DR    = 3'd5; // digging, will resume right
    localparam SPLAT = 3'd6; // splattered (all outputs 0, forever)

    reg [2:0] state, next;
    reg [5:0] fall_cnt; // 1-indexed: = number of fall cycles elapsed (incl. current)

    // The Lemming splatters if it falls for MORE THAN 20 cycles then hits ground.
    // fall_cnt is 1-indexed (it equals 1 on the very first fall cycle, L on the
    // L-th fall cycle), so on the landing cycle "fell for L cycles" => splat iff
    // L > 20.
    wire too_long = (fall_cnt > 6'd20);

    always @(*) begin
        case (state)
            // Walking: priority fall (ground=0) > dig > switch-direction (bump).
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
            // Falling: stay until ground returns; then splatter if fell too long.
            FL: begin
                if (!ground)       next = FL;
                else if (too_long) next = SPLAT;
                else               next = WL;
            end
            FR: begin
                if (!ground)       next = FR;
                else if (too_long) next = SPLAT;
                else               next = WR;
            end
            // Digging: continue until ground disappears, then fall.
            DL:    next = ground ? DL : FL;
            DR:    next = ground ? DR : FR;
            SPLAT: next = SPLAT;
            default: next = WL;
        endcase
    end

    always @(posedge clk or posedge areset) begin
        if (areset) begin
            state    <= WL;
            fall_cnt <= 6'd0;
        end else begin
            state <= next;
            // 1-indexed fall-cycle counter: increment whenever the NEXT state is a
            // falling state (so it reads 1 on the first fall cycle), saturating;
            // clear whenever we are not about to be falling.
            if (next == FL || next == FR) begin
                if (fall_cnt < 6'd63) fall_cnt <= fall_cnt + 6'd1;
            end else begin
                fall_cnt <= 6'd0;
            end
        end
    end

    assign walk_left  = (state == WL);
    assign walk_right = (state == WR);
    assign aaah       = (state == FL) || (state == FR);
    assign digging    = (state == DL) || (state == DR);
endmodule
