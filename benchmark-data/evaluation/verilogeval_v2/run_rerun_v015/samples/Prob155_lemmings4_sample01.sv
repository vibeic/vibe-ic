module TopModule(
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
    localparam WL    = 3'd0; // walk left
    localparam WR    = 3'd1; // walk right
    localparam DL    = 3'd2; // digging, originally left
    localparam DR    = 3'd3; // digging, originally right
    localparam FL    = 3'd4; // falling, originally left
    localparam FR    = 3'd5; // falling, originally right
    localparam SPLAT = 3'd6; // splattered

    reg [2:0]  state, next;
    reg [31:0] fall_cnt; // number of cycles spent falling, incl. current cycle

    // A fall lasting more than 20 cycles -> splatter on hitting ground
    wire too_long = (fall_cnt > 32'd20);

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
            DL: next = ground ? DL : FL;
            DR: next = ground ? DR : FR;
            FL: next = ground ? (too_long ? SPLAT : WL) : FL;
            FR: next = ground ? (too_long ? SPLAT : WR) : FR;
            SPLAT: next = SPLAT;
            default: next = WL;
        endcase
    end

    always @(posedge clk or posedge areset) begin
        if (areset) begin
            state    <= WL;
            fall_cnt <= 32'd0;
        end else begin
            state <= next;
            // count consecutive falling cycles, including the first
            if (next == FL || next == FR) begin
                if (state == FL || state == FR)
                    fall_cnt <= fall_cnt + 32'd1; // continuing to fall
                else
                    fall_cnt <= 32'd1;            // first cycle of this fall
            end else begin
                fall_cnt <= 32'd0;
            end
        end
    end

    assign walk_left  = (state == WL);
    assign walk_right = (state == WR);
    assign aaah       = (state == FL) || (state == FR);
    assign digging    = (state == DL) || (state == DR);
endmodule
