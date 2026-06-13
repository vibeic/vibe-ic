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
    // pattern-detect 1101, then 4 shift cycles, count, done
    localparam S    = 4'd0;   // searching: seen nothing / start
    localparam S1   = 4'd1;   // seen 1
    localparam S11  = 4'd2;   // seen 11
    localparam S110 = 4'd3;   // seen 110
    localparam B0   = 4'd4;   // 1101 detected -> shift bit 0
    localparam B1   = 4'd5;
    localparam B2   = 4'd6;
    localparam B3   = 4'd7;
    localparam CNT  = 4'd8;   // counting
    localparam WAIT = 4'd9;   // done, wait for ack

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
        if (reset) state <= S;
        else       state <= next;
    end

    assign shift_ena = (state == B0) || (state == B1) || (state == B2) || (state == B3);
    assign counting  = (state == CNT);
    assign done      = (state == WAIT);
endmodule
