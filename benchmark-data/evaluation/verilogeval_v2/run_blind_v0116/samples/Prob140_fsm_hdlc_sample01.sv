module TopModule (
    input  clk,
    input  reset,
    input  in,
    output disc,
    output flag,
    output err
);
    // States count consecutive 1s. ERR is sticky until a 0 arrives.
    localparam S0   = 4'd0;   // saw a 0 (or reset): 0 consecutive 1s
    localparam S1   = 4'd1;   // 1 one
    localparam S2   = 4'd2;
    localparam S3   = 4'd3;
    localparam S4   = 4'd4;
    localparam S5   = 4'd5;   // 5 ones
    localparam S6   = 4'd6;   // 6 ones
    localparam DISC = 4'd7;   // just saw 0 after exactly 5 ones
    localparam FLAG = 4'd8;   // just saw 0 after exactly 6 ones
    localparam ERR  = 4'd9;   // 7+ ones, stays until a 0

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            S0:   next = in ? S1   : S0;
            S1:   next = in ? S2   : S0;
            S2:   next = in ? S3   : S0;
            S3:   next = in ? S4   : S0;
            S4:   next = in ? S5   : S0;
            S5:   next = in ? S6   : DISC;   // 5 ones then 0 -> discard
            S6:   next = in ? ERR  : FLAG;   // 6 ones then 0 -> flag ; 7th one -> err
            DISC: next = in ? S1   : S0;     // the terminating 0 already consumed; new bit
            FLAG: next = in ? S1   : S0;
            ERR:  next = in ? ERR  : S0;     // stay in err on 1s, clear on 0
            default: next = S0;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= S0;
        else
            state <= next;
    end

    // Moore outputs: asserted while in the DISC/FLAG/ERR states (one cycle after condition).
    assign disc = (state == DISC);
    assign flag = (state == FLAG);
    assign err  = (state == ERR);
endmodule
