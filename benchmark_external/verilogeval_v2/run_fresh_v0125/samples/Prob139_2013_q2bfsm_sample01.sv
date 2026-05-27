module TopModule (
    input  clk,
    input  resetn,
    input  x,
    input  y,
    output f,
    output g
);

    localparam A      = 4'd0,  // reset state
               F1     = 4'd1,  // assert f for one cycle
               X1     = 4'd2,  // wait for x=1 (first of 1,0,1)
               X2     = 4'd3,  // saw 1, wait for x=0
               X3     = 4'd4,  // saw 1,0, wait for x=1
               GY1    = 4'd5,  // g=1, first y-monitoring cycle
               GY2    = 4'd6,  // g=1, second y-monitoring cycle
               GHOLD  = 4'd7,  // g=1 permanently
               GOFF   = 4'd8;  // g=0 permanently

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            A:     next = F1;
            F1:    next = X1;
            X1:    next = x ? X2 : X1;
            X2:    next = x ? X2 : X3;        // need a 0 next; on 1 stay (new leading 1)
            X3:    next = x ? GY1 : X1;       // saw 1,0,1 -> go monitor y
            GY1:   next = y ? GHOLD : GY2;    // y within first cycle -> hold
            GY2:   next = y ? GHOLD : GOFF;   // y within second cycle -> hold else off
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
    assign g = (state == GY1) || (state == GY2) ||
               (state == GHOLD);

endmodule
