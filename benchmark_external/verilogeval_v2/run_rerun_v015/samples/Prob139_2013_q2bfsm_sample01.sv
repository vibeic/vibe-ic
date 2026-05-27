module TopModule (
    input  clk,
    input  resetn,
    input  x,
    input  y,
    output f,
    output g
);

    localparam A     = 4'd0,   // reset / begin state
               F1    = 4'd1,   // assert f for one cycle
               S0    = 4'd2,   // looking for first 1 of "101"
               S1    = 4'd3,   // history "1"
               S2    = 4'd4,   // history "10"
               G0    = 4'd5,   // g=1, first y-watch cycle
               G1    = 4'd6,   // g=1, second y-watch cycle
               GHOLD = 4'd7,   // g=1 permanently
               GOFF  = 4'd8;   // g=0 permanently

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            A:     next = F1;
            F1:    next = S0;
            S0:    next = x ? S1 : S0;
            S1:    next = x ? S1 : S2;
            S2:    next = x ? G0 : S0;
            G0:    next = y ? GHOLD : G1;
            G1:    next = y ? GHOLD : GOFF;
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

    assign f = (state == F1);
    assign g = (state == G0) || (state == G1) || (state == GHOLD);

endmodule
