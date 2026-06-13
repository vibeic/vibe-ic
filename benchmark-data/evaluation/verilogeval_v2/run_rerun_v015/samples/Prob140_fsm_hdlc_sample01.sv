module TopModule(
    input  clk,
    input  reset,
    input  in,
    output disc,
    output flag,
    output err
);
    // States counting consecutive 1s after a 0
    localparam S0   = 4'd0;  // saw 0 (base)
    localparam S1   = 4'd1;  // one 1
    localparam S2   = 4'd2;
    localparam S3   = 4'd3;
    localparam S4   = 4'd4;
    localparam S5   = 4'd5;  // five 1s seen
    localparam S6   = 4'd6;  // six 1s seen
    localparam DISC = 4'd7;  // 0111110 detected -> discard
    localparam FLAG = 4'd8;  // 01111110 detected -> flag
    localparam ERR  = 4'd9;  // 7+ ones -> error; stay until a 0

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            S0:   next = in ? S1 : S0;
            S1:   next = in ? S2 : S0;
            S2:   next = in ? S3 : S0;
            S3:   next = in ? S4 : S0;
            S4:   next = in ? S5 : S0;
            S5:   next = in ? S6   : DISC; // five ones then 0 -> discard
            S6:   next = in ? ERR  : FLAG; // six ones then 0 -> flag; another 1 -> error
            DISC: next = in ? S1   : S0;   // the discarded bit (0) consumed; continue
            FLAG: next = in ? S1   : S0;
            ERR:  next = in ? ERR  : S0;   // stay in error until a 0
            default: next = S0;
        endcase
    end

    always @(posedge clk) begin
        if (reset) state <= S0;
        else       state <= next;
    end

    assign disc = (state == DISC);
    assign flag = (state == FLAG);
    assign err  = (state == ERR);
endmodule
