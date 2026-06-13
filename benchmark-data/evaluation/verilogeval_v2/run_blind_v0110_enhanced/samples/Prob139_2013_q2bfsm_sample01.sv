module TopModule(
    input  clk,
    input  resetn,
    input  x,
    input  y,
    output f,
    output g
);
    localparam S_A    = 4'd0,  // begin/reset state (f=0,g=0)
               S_F    = 4'd1,  // f=1 for one cycle
               X_IDLE = 4'd2,  // monitor x, no progress
               X_1    = 4'd3,  // saw '1'
               X_10   = 4'd4,  // saw '10'
               G_W1   = 4'd5,  // g=1, first y-watch cycle
               G_W2   = 4'd6,  // g=1, second y-watch cycle
               G_HOLD = 4'd7,  // g=1 forever
               G_OFF  = 4'd8;  // g=0 forever

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            S_A:    next = S_F;                       // leave begin state -> pulse f
            S_F:    next = X_IDLE;                    // f=1 one cycle, then monitor x
            X_IDLE: next = x ? X_1 : X_IDLE;
            X_1:    next = x ? X_1 : X_10;            // overlapping
            X_10:   next = x ? G_W1 : X_IDLE;         // '101' detected -> g region
            G_W1:   next = y ? G_HOLD : G_W2;
            G_W2:   next = y ? G_HOLD : G_OFF;
            G_HOLD: next = G_HOLD;
            G_OFF:  next = G_OFF;
            default: next = S_A;
        endcase
    end

    always @(posedge clk) begin
        if (!resetn)
            state <= S_A;
        else
            state <= next;
    end

    assign f = (state == S_F);
    assign g = (state == G_W1) || (state == G_W2) ||
               (state == G_HOLD);
endmodule
