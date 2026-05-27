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
    localparam WL = 3'd0, WR = 3'd1, FL = 3'd2, FR = 3'd3,
               DL = 3'd4, DR = 3'd5, SPLAT = 3'd6;
    reg [2:0] state, next;
    reg [4:0] fall_cnt;   // counts cycles spent falling (saturating at >20)

    // landing after falling more than 20 cycles -> splatter
    wire splat_on_land = (fall_cnt > 5'd20);

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
            FL: next = ground ? (splat_on_land ? SPLAT : WL) : FL;
            FR: next = ground ? (splat_on_land ? SPLAT : WR) : FR;
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
            if ((state == FL) || (state == FR)) begin
                if (fall_cnt <= 5'd20) fall_cnt <= fall_cnt + 5'd1;
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
