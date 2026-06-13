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
    // states: search pattern 1101, then 4 shift cycles, then count, then wait-ack
    localparam S    = 4'd0,  // looking for first 1
               S1   = 4'd1,  // saw 1
               S11  = 4'd2,  // saw 11
               S110 = 4'd3,  // saw 110
               B0   = 4'd4,  // shift cycle 1 (after 1101)
               B1   = 4'd5,
               B2   = 4'd6,
               B3   = 4'd7,
               CNT  = 4'd8,  // counting
               WAITS= 4'd9;  // waiting for ack (done)
    reg [3:0] state, next;

    always @(*) begin
        case (state)
            S    : next = data ? S1   : S;
            S1   : next = data ? S11  : S;
            S11  : next = data ? S11  : S110;
            S110 : next = data ? B0   : S;
            B0   : next = B1;
            B1   : next = B2;
            B2   : next = B3;
            B3   : next = CNT;
            CNT  : next = done_counting ? WAITS : CNT;
            WAITS: next = ack ? S : WAITS;
            default: next = S;
        endcase
    end

    always @(posedge clk) begin
        if (reset) state <= S;
        else       state <= next;
    end

    assign shift_ena = (state == B0) || (state == B1) || (state == B2) || (state == B3);
    assign counting  = (state == CNT);
    assign done      = (state == WAITS);
endmodule
