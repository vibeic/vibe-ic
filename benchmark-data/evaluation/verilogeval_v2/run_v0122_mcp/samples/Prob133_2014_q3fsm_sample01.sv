module TopModule (
    input  clk,
    input  reset,
    input  s,
    input  w,
    output z
);

    // State A waits for s. Once s=1, examine w over 3-cycle windows.
    // Track number of w samples taken in the current window (0..2 before
    // the 3rd) and the running count of ones. After the 3rd sample, z is
    // asserted in the following cycle iff the window had exactly two ones;
    // that same cycle is sample-1 of the next window.
    localparam A   = 3'd0,  // idle
               S0  = 3'd1,  // window open, 0 samples taken
               S1_0= 3'd2,  // 1 sample, 0 ones
               S1_1= 3'd3,  // 1 sample, 1 one
               S2_0= 3'd4,  // 2 samples, 0 ones
               S2_1= 3'd5,  // 2 samples, 1 one
               S2_2= 3'd6;  // 2 samples, 2 ones

    reg [2:0] state, nxt;
    reg       z_r;

    // Helper: given current "1-sample" start, build next from a fresh sample.
    // After the 3rd sample we restart: the new window's first sample is w.
    always @(*) begin
        case (state)
            A:    nxt = s ? S0 : A;
            S0:   nxt = w ? S1_1 : S1_0;
            S1_0: nxt = w ? S2_1 : S2_0;
            S1_1: nxt = w ? S2_2 : S2_1;
            // 3rd sample taken here -> restart window with this same w as sample 1
            S2_0: nxt = w ? S1_1 : S1_0;  // total ones = 0 or 1 -> z=0 next
            S2_1: nxt = w ? S1_1 : S1_0;  // total ones = 1 or 2
            S2_2: nxt = w ? S1_1 : S1_0;  // total ones = 2 or 3
            default: nxt = A;
        endcase
    end

    // z is asserted the cycle after a window completes with exactly two ones.
    // Completion happens on the transition out of S2_*; the third sample is w.
    //   S2_0 + w=1 -> total 1 (no), w=0 -> 0 (no)               => z=0
    //   S2_1 + w=1 -> total 2 (YES), w=0 -> 1 (no)              => z = w
    //   S2_2 + w=1 -> total 3 (no),  w=0 -> 2 (YES)             => z = ~w
    always @(*) begin
        case (state)
            S2_1: z_r = w;
            S2_2: z_r = ~w;
            default: z_r = 1'b0;
        endcase
    end

    reg z_out;
    always @(posedge clk) begin
        if (reset) begin
            state <= A;
            z_out <= 1'b0;
        end else begin
            state <= nxt;
            z_out <= z_r;   // registered: asserted in the FOLLOWING cycle
        end
    end

    assign z = z_out;

endmodule
