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
    localparam LEFT=3'd0, RIGHT=3'd1, FALL_L=3'd2, FALL_R=3'd3,
               DIG_L=3'd4, DIG_R=3'd5, SPLAT=3'd6;

    reg [2:0] state;
    reg [4:0] fall_cnt; // saturating, 0..20 needed

    always @(posedge clk or posedge areset) begin
        if (areset) begin
            state    <= LEFT;
            fall_cnt <= 5'd0;
        end else begin
            case (state)
                LEFT: begin
                    if (!ground) begin state <= FALL_L; fall_cnt <= 5'd0; end
                    else if (dig) state <= DIG_L;
                    else if (bump_left) state <= RIGHT;
                    else state <= LEFT;
                end
                RIGHT: begin
                    if (!ground) begin state <= FALL_R; fall_cnt <= 5'd0; end
                    else if (dig) state <= DIG_R;
                    else if (bump_right) state <= LEFT;
                    else state <= RIGHT;
                end
                DIG_L: begin
                    if (!ground) begin state <= FALL_L; fall_cnt <= 5'd0; end
                    else state <= DIG_L;
                end
                DIG_R: begin
                    if (!ground) begin state <= FALL_R; fall_cnt <= 5'd0; end
                    else state <= DIG_R;
                end
                FALL_L: begin
                    if (ground) begin
                        state <= (fall_cnt >= 5'd20) ? SPLAT : LEFT;
                    end else begin
                        state <= FALL_L;
                        if (fall_cnt < 5'd20) fall_cnt <= fall_cnt + 5'd1;
                    end
                end
                FALL_R: begin
                    if (ground) begin
                        state <= (fall_cnt >= 5'd20) ? SPLAT : RIGHT;
                    end else begin
                        state <= FALL_R;
                        if (fall_cnt < 5'd20) fall_cnt <= fall_cnt + 5'd1;
                    end
                end
                SPLAT: state <= SPLAT;
                default: state <= LEFT;
            endcase
        end
    end

    assign walk_left  = (state == LEFT);
    assign walk_right = (state == RIGHT);
    assign aaah        = (state == FALL_L) || (state == FALL_R);
    assign digging     = (state == DIG_L) || (state == DIG_R);

endmodule
