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
    // States: walking, digging, falling (direction-tracked), splattered.
    localparam WL    = 4'd0;  // walk left
    localparam WR    = 4'd1;  // walk right
    localparam DIGL  = 4'd2;  // digging, original direction left
    localparam DIGR  = 4'd3;  // digging, original direction right
    localparam FALLL = 4'd4;  // falling, original direction left
    localparam FALLR = 4'd5;  // falling, original direction right
    localparam SPLAT = 4'd6;  // splattered (terminal)

    reg [3:0]  state, next;
    // Fall-duration counter: counts clock cycles spent in a FALL state.
    // Splatter if falling > 20 cycles then hits ground.
    reg [31:0] fall_cnt;

    // precedence while walking: fall > dig > switch direction
    always @(*) begin
        next = state;
        case (state)
            WL: begin
                if (!ground)      next = FALLL;
                else if (dig)     next = DIGL;
                else if (bump_left)  next = WR;
                else              next = WL;
            end
            WR: begin
                if (!ground)      next = FALLR;
                else if (dig)     next = DIGR;
                else if (bump_right) next = WL;
                else              next = WR;
            end
            DIGL: begin
                if (!ground)      next = FALLL;   // reached other side -> fall
                else              next = DIGL;
            end
            DIGR: begin
                if (!ground)      next = FALLR;
                else              next = DIGR;
            end
            FALLL: begin
                if (ground)       next = (fall_cnt > 20) ? SPLAT : WL;
                else              next = FALLL;
            end
            FALLR: begin
                if (ground)       next = (fall_cnt > 20) ? SPLAT : WR;
                else              next = FALLR;
            end
            SPLAT: next = SPLAT;  // terminal
            default: next = WL;
        endcase
    end

    always @(posedge clk or posedge areset) begin
        if (areset) begin
            state    <= WL;
            fall_cnt <= 32'd0;
        end else begin
            state <= next;
            // Inclusive fall-cycle counter: 1 on the first fall cycle, then +1
            // each subsequent fall cycle, 0 whenever not falling. So while in a
            // FALL state at fall-cycle m, fall_cnt == m, and "fell more than 20
            // cycles" maps exactly to (fall_cnt > 20) tested in the FALL state.
            if (next == FALLL || next == FALLR) begin
                if (state == FALLL || state == FALLR)
                    fall_cnt <= fall_cnt + 32'd1;
                else
                    fall_cnt <= 32'd1;
            end else
                fall_cnt <= 32'd0;
        end
    end

    // Moore outputs (function of current state only).
    assign walk_left  = (state == WL);
    assign walk_right = (state == WR);
    assign aaah       = (state == FALLL) || (state == FALLR);
    assign digging    = (state == DIGL)  || (state == DIGR);
endmodule
