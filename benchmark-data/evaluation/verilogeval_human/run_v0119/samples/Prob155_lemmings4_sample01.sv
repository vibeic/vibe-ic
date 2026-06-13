module TopModule (
  input clk,
  input areset,
  input bump_left,
  input bump_right,
  input ground,
  input dig,
  output walk_left,
  output walk_right,
  output aaah,
  output digging
);
    localparam WL    = 3'd0,
               WR    = 3'd1,
               FL    = 3'd2,  // fall, was left
               FR    = 3'd3,  // fall, was right
               DL    = 3'd4,  // dig, was left
               DR    = 3'd5,  // dig, was right
               SPLAT = 3'd6;

    reg [2:0] state, next;
    reg [4:0] cnt;            // counts cycles spent falling (saturates)

    wire too_long = (cnt > 5'd20);

    always @(*) begin
        case (state)
            WL: if (!ground)        next = FL;
                else if (dig)       next = DL;
                else if (bump_left) next = WR;
                else                next = WL;
            WR: if (!ground)         next = FR;
                else if (dig)        next = DR;
                else if (bump_right) next = WL;
                else                 next = WR;
            FL: if (ground) next = too_long ? SPLAT : WL;
                else        next = FL;
            FR: if (ground) next = too_long ? SPLAT : WR;
                else        next = FR;
            DL: next = ground ? DL : FL;
            DR: next = ground ? DR : FR;
            SPLAT: next = SPLAT;
            default: next = WL;
        endcase
    end

    always @(posedge clk or posedge areset) begin
        if (areset) begin
            state <= WL;
            cnt   <= 5'd0;
        end else begin
            state <= next;
            // count cycles while next-state is a fall state
            if (next == FL || next == FR)
                cnt <= (cnt == 5'd31) ? 5'd31 : cnt + 5'd1;
            else
                cnt <= 5'd0;
        end
    end

    assign walk_left  = (state == WL);
    assign walk_right = (state == WR);
    assign aaah       = (state == FL) || (state == FR);
    assign digging    = (state == DL) || (state == DR);
endmodule
