module TopModule (
    input  clk,
    input  reset,
    input  in,
    output disc,
    output flag,
    output err
);
    // Moore FSM. Count consecutive 1s. Outputs are registered (asserted the
    // cycle after the recognizing input).
    // States track number of consecutive 1s seen so far (0..6) plus
    // dedicated DISC/FLAG/ERR states that produce the one-cycle output.
    localparam S0   = 4'd0;  // 0 consecutive ones
    localparam S1   = 4'd1;
    localparam S2   = 4'd2;
    localparam S3   = 4'd3;
    localparam S4   = 4'd4;
    localparam S5   = 4'd5;  // 5 consecutive ones
    localparam S6   = 4'd6;  // 6 consecutive ones
    localparam DISC = 4'd7;  // saw 0111110 -> bit to discard
    localparam FLAG = 4'd8;  // saw 01111110
    localparam ERR  = 4'd9;  // saw 7+ ones, hold until a 0 arrives

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            S0:   next = in ? S1 : S0;
            S1:   next = in ? S2 : S0;
            S2:   next = in ? S3 : S0;
            S3:   next = in ? S4 : S0;
            S4:   next = in ? S5 : S0;
            S5:   next = in ? S6   : DISC; // 5 ones then 0 => discard
            S6:   next = in ? ERR  : FLAG; // 6 ones then 0 => flag; then 1 => err
            DISC: next = in ? S1 : S0;     // discard state, resume counting
            FLAG: next = in ? S1 : S0;
            ERR:  next = in ? ERR : S0;    // stay in error until a 0
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
