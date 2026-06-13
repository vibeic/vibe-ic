module TopModule (
    input  clk,
    input  reset,
    input  in,
    output disc,
    output flag,
    output err
);

    // States: count consecutive 1s seen so far, with handling of zeros.
    localparam S0    = 4'd0;  // saw 0 (or initial)
    localparam S1    = 4'd1;  // 1
    localparam S2    = 4'd2;  // 11
    localparam S3    = 4'd3;  // 111
    localparam S4    = 4'd4;  // 1111
    localparam S5    = 4'd5;  // 11111
    localparam S6    = 4'd6;  // 111111
    localparam DISC  = 4'd7;  // after 0111110 -> discard
    localparam FLAG  = 4'd8;  // after 01111110 -> flag
    localparam ERR   = 4'd9;  // 7 or more ones -> error

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            S0:   next = in ? S1 : S0;
            S1:   next = in ? S2 : S0;
            S2:   next = in ? S3 : S0;
            S3:   next = in ? S4 : S0;
            S4:   next = in ? S5 : S0;
            S5:   next = in ? S6 : DISC;   // 11111 then 0 -> discard
            S6:   next = in ? ERR : FLAG;  // 111111 then 0 -> flag, then 1 -> err
            DISC: next = in ? S1 : S0;
            FLAG: next = in ? S1 : S0;
            ERR:  next = in ? ERR : S0;    // stay in err while 1s continue
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
