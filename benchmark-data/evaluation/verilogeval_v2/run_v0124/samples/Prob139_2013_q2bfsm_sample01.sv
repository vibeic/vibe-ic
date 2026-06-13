module TopModule (
    input  clk,
    input  resetn,
    input  x,
    input  y,
    output f,
    output g
);

    localparam A     = 4'd0,  // reset / idle, f=0 g=0
               S_F   = 4'd1,  // f=1 for one cycle
               S0    = 4'd2,  // x-detect: no progress
               S1    = 4'd3,  // saw 1
               S2    = 4'd4,  // saw 10
               G1    = 4'd5,  // g=1, first y check
               G2    = 4'd6,  // g=1, second y check
               GHOLD = 4'd7,  // g=1 permanently
               GOFF  = 4'd8;  // g=0 permanently

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            A:     next = S_F;
            S_F:   next = S0;
            S0:    next = x ? S1 : S0;
            S1:    next = x ? S1 : S2;
            S2:    next = x ? G1 : S0;
            G1:    next = y ? GHOLD : G2;
            G2:    next = y ? GHOLD : GOFF;
            GHOLD: next = GHOLD;
            GOFF:  next = GOFF;
            default: next = A;
        endcase
    end

    always @(posedge clk) begin
        if (!resetn)
            state <= A;
        else
            state <= next;
    end

    assign f = (state == S_F);
    assign g = (state == G1) || (state == G2) || (state == GHOLD);

endmodule
