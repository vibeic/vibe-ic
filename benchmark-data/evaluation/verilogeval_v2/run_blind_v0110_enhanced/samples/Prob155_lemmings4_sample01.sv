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
    localparam WL=3'd0, WR=3'd1, FL=3'd2, FR=3'd3, DL=3'd4, DR=3'd5, SPLAT=3'd6;
    reg [2:0] state, next;
    reg [5:0] fcnt;        // cycles spent falling (saturating)

    wire falling = (state == FL) || (state == FR);
    wire too_long = (fcnt > 6'd20);   // fell more than 20 cycles

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
            state <= WL;
            fcnt  <= 6'd0;
        end else begin
            state <= next;
            // fcnt = number of cycles already spent falling.
            // It increments each cycle we remain in a falling state, and
            // resets to 1 on the first falling cycle (entering fall).
            if (falling)
                fcnt <= (fcnt == 6'd63) ? fcnt : fcnt + 6'd1;
            else
                fcnt <= 6'd1;   // priming: first fall cycle counts as 1
        end
    end

    assign walk_left  = (state == WL);
    assign walk_right = (state == WR);
    assign aaah       = (state == FL) || (state == FR);
    assign digging    = (state == DL) || (state == DR);
endmodule
