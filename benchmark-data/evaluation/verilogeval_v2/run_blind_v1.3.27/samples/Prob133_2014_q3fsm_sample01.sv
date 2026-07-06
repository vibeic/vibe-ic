module TopModule (
    input  clk,
    input  reset,
    input  s,
    input  w,
    output z
);

    // A     : reset state, waiting for s
    // S0    : start of a 3-cycle window, 0 ones so far (also "z=0" resting
    //         state entered after a window that did NOT have exactly 2 ones)
    // S1_0  : 1 cycle into window, 0 ones seen
    // S1_1  : 1 cycle into window, 1 one seen
    // S2_0  : 2 cycles into window, 0 ones seen
    // S2_1  : 2 cycles into window, 1 one seen
    // S2_2  : 2 cycles into window, 2 ones seen
    // S3    : window just completed with exactly 2 ones -> z=1 this cycle;
    //         behaves like S0 for starting the next window
    localparam A    = 3'd0,
               S0   = 3'd1,
               S1_0 = 3'd2,
               S1_1 = 3'd3,
               S2_0 = 3'd4,
               S2_1 = 3'd5,
               S2_2 = 3'd6,
               S3   = 3'd7;

    reg [2:0] state, next_state;

    always @(*) begin
        case (state)
            A:    next_state = s ? S0 : A;
            S0:   next_state = w ? S1_1 : S1_0;
            S1_0: next_state = w ? S2_1 : S2_0;
            S1_1: next_state = w ? S2_2 : S2_1;
            S2_0: next_state = S0;                 // 0 or 1 ones -> z=0
            S2_1: next_state = w ? S3 : S0;        // +1 -> 2 ones(z=1) or 1 one(z=0)
            S2_2: next_state = w ? S0 : S3;        // +1 -> 3 ones(z=0) or 2 ones(z=1)
            S3:   next_state = w ? S1_1 : S1_0;    // start next window like S0
            default: next_state = A;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= A;
        else
            state <= next_state;
    end

    assign z = (state == S3);

endmodule
