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

    // Moore FSM (lemmings3 + splat). A Lemming that falls for MORE than 20
    // clock cycles and then hits the ground splatters (all four outputs 0,
    // forever). fall_cnt is 0-based: it is reset to 0 the cycle a FALL state is
    // entered and saturates at 20 while falling. At the hit-ground transition,
    // fall_cnt >= 20 means it fell more than 20 cycles -> SPLAT. Splat only on
    // landing; no upper limit on fall length. Async reset to WALK_L.
    localparam WALK_L=3'd0, WALK_R=3'd1, FALL_L=3'd2, FALL_R=3'd3,
               DIG_L =3'd4, DIG_R =3'd5, SPLAT=3'd6;

    reg [2:0] state, next;
    reg [4:0] fall_cnt;     // saturates at 20

    wire too_long = (fall_cnt >= 5'd20);

    always @(*) begin
        case (state)
            WALK_L: if (!ground)        next = FALL_L;
                    else if (dig)       next = DIG_L;
                    else if (bump_left) next = WALK_R;
                    else                next = WALK_L;
            WALK_R: if (!ground)         next = FALL_R;
                    else if (dig)        next = DIG_R;
                    else if (bump_right) next = WALK_L;
                    else                 next = WALK_R;
            FALL_L: if (!ground)        next = FALL_L;
                    else                next = too_long ? SPLAT : WALK_L;
            FALL_R: if (!ground)        next = FALL_R;
                    else                next = too_long ? SPLAT : WALK_R;
            DIG_L:  next = ground ? DIG_L : FALL_L;
            DIG_R:  next = ground ? DIG_R : FALL_R;
            SPLAT:  next = SPLAT;
            default: next = WALK_L;
        endcase
    end

    always @(posedge clk or posedge areset) begin
        if (areset) begin
            state    <= WALK_L;
            fall_cnt <= 0;
        end else begin
            state <= next;
            // fall_cnt counts cycles spent in a FALL state (0-based, sat at 20)
            if (next == FALL_L || next == FALL_R) begin
                if (state == FALL_L || state == FALL_R) begin
                    if (fall_cnt < 5'd20) fall_cnt <= fall_cnt + 1'b1;
                end else begin
                    fall_cnt <= 0;       // just entered a FALL state
                end
            end else begin
                fall_cnt <= 0;
            end
        end
    end

    assign walk_left  = (state == WALK_L);
    assign walk_right = (state == WALK_R);
    assign aaah       = (state == FALL_L) || (state == FALL_R);
    assign digging    = (state == DIG_L)  || (state == DIG_R);

endmodule
