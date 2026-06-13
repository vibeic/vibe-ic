module TopModule (
    input  clk,
    input  reset,
    input  s,
    input  w,
    output z
);
    // A      : idle, waiting for s.
    // Sj_k   : in a 3-cycle window, having taken j samples so far with k ones,
    //          ABOUT to sample w this cycle as sample (j+1).
    //   slot 0 (S0*): sample #1 of the window
    //   slot 1 (S1*): sample #2
    //   slot 2 (S2*): sample #3
    // After the 3rd sample we go to a slot-0 state of the NEXT window; if the just-finished
    // window had exactly two ones, that slot-0 state also asserts z (so z is high for exactly
    // the one cycle after the window, and that cycle is sample #1 of the next window).
    localparam A     = 4'd0,
               S0    = 4'd1,  // start window, z=0
               S0z   = 4'd2,  // start window, z=1 (previous window accepted)
               S1_0  = 4'd3,  // 1 sample taken, 0 ones
               S1_1  = 4'd4,  // 1 sample taken, 1 one
               S2_0  = 4'd5,  // 2 samples, 0 ones
               S2_1  = 4'd6,  // 2 samples, 1 one
               S2_2  = 4'd7;  // 2 samples, 2 ones

    reg [3:0] state, nstate;

    // sample slot0 helper: from a "start window" state, take sample #1 (=w)
    // and move to the 1-sample state with that ones-count.
    always @(*) begin
        case (state)
            A:    nstate = s ? S0 : A;

            // slot0: take sample #1
            S0:   nstate = w ? S1_1 : S1_0;
            S0z:  nstate = w ? S1_1 : S1_0;

            // slot1: take sample #2
            S1_0: nstate = w ? S2_1 : S2_0;
            S1_1: nstate = w ? S2_2 : S2_1;

            // slot2: take sample #3, then go to next window's slot0,
            // asserting z (S0z) iff total ones == 2.
            S2_0: nstate = w ? S0   : S0;    // ones 0 or 1 -> not accept
            S2_1: nstate = w ? S0z  : S0;    // 1 + w : 2 ones if w=1 -> accept
            S2_2: nstate = w ? S0   : S0z;   // 2 + w : 2 ones if w=0 -> accept
            default: nstate = A;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= A;
        else
            state <= nstate;
    end

    // Moore output: z high only in the S0z (accept) start-of-window state.
    assign z = (state == S0z);
endmodule
