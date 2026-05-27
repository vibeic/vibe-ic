module TopModule (
    input  clk,
    input  reset,
    input  data,
    input  done_counting,
    input  ack,
    output shift_ena,
    output counting,
    output done
);
    localparam S    = 4'd0,   // searching, last bits matched: none
               S1   = 4'd1,   // matched "1"
               S11  = 4'd2,   // matched "11"
               S110 = 4'd3,   // matched "110"
               B0   = 4'd4,   // 1101 found; shift_ena cycle 1
               B1   = 4'd5,   // shift_ena cycle 2
               B2   = 4'd6,   // shift_ena cycle 3
               B3   = 4'd7,   // shift_ena cycle 4
               CNT  = 4'd8,   // counting
               WAIT = 4'd9;   // done, waiting for ack

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            S:    next = data ? S1   : S;
            S1:   next = data ? S11  : S;
            S11:  next = data ? S11  : S110;
            S110: next = data ? B0   : S;
            B0:   next = B1;
            B1:   next = B2;
            B2:   next = B3;
            B3:   next = CNT;
            CNT:  next = done_counting ? WAIT : CNT;
            WAIT: next = ack ? S : WAIT;
            default: next = S;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= S;
        else
            state <= next;
    end

    assign shift_ena = (state == B0) || (state == B1) || (state == B2) || (state == B3);
    assign counting  = (state == CNT);
    assign done      = (state == WAIT);
endmodule
