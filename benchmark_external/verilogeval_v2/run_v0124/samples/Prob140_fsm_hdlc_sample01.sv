module TopModule (
    input  clk,
    input  reset,
    input  in,
    output disc,
    output flag,
    output err
);

    localparam S0   = 4'd0,  // previous input was 0 (count 0)
               S1   = 4'd1,  // 1 consecutive 1
               S2   = 4'd2,
               S3   = 4'd3,
               S4   = 4'd4,
               S5   = 4'd5,  // 5 consecutive 1s
               S6   = 4'd6,  // 6 consecutive 1s
               DISC = 4'd7,  // saw 0111110
               FLAG = 4'd8,  // saw 01111110
               ERR  = 4'd9;  // 7 or more consecutive 1s

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            S0:   next = in ? S1 : S0;
            S1:   next = in ? S2 : S0;
            S2:   next = in ? S3 : S0;
            S3:   next = in ? S4 : S0;
            S4:   next = in ? S5 : S0;
            S5:   next = in ? S6   : DISC;
            S6:   next = in ? ERR  : FLAG;
            DISC: next = in ? S1 : S0;
            FLAG: next = in ? S1 : S0;
            ERR:  next = in ? ERR : S0;
            default: next = S0;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= S0;
        else
            state <= next;
    end

    assign disc = (state == DISC);
    assign flag = (state == FLAG);
    assign err  = (state == ERR);

endmodule
