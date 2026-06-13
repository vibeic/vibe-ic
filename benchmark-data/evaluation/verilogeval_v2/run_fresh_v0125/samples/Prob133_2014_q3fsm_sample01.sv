module TopModule (
    input  clk,
    input  reset,
    input  s,
    input  w,
    output reg z
);

    // States:
    //  A           : wait for s
    //  S0          : about to take first w sample of a group (count starts at 0)
    //  S1_c0/S1_c1 : after 1 sample, count of w so far = 0 or 1
    //  S2_c0/c1/c2 : after 2 samples, count = 0,1,2
    // Output decision happens after the 3rd sample.
    localparam A     = 4'd0,
               G0    = 4'd1,   // start of a group, 0 samples taken, count=0
               G1c0  = 4'd2,   // 1 sample taken, count 0
               G1c1  = 4'd3,   // 1 sample taken, count 1
               G2c0  = 4'd4,   // 2 samples taken, count 0
               G2c1  = 4'd5,   // 2 samples taken, count 1
               G2c2  = 4'd6;   // 2 samples taken, count 2

    reg [3:0] state, next;

    // next state: in G* states we are about to sample w this cycle then advance
    always @(*) begin
        case (state)
            A:    next = s ? G0 : A;
            // In G0 we sample w (first of group)
            G0:   next = w ? G1c1 : G1c0;
            G1c0: next = w ? G2c1 : G2c0;
            G1c1: next = w ? G2c2 : G2c1;
            // After 3rd sample, return to start of next group (G0)
            G2c0: next = G0;   // counts: 0 + w(3rd)
            G2c1: next = G0;
            G2c2: next = G0;
            default: next = A;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= A;
        else
            state <= next;
    end

    // z is asserted in the cycle AFTER the 3rd sample if exactly two w=1 seen.
    // The 3rd sample is taken while in G2c* ; total count = prior count + w.
    // exactly two => (G2c1 & w) or (G2c2 & ~w).
    // z must be high during the following cycle (which is the new group's G0 cycle).
    reg z_pending;
    always @(posedge clk) begin
        if (reset)
            z_pending <= 1'b0;
        else begin
            case (state)
                G2c0: z_pending <= 1'b0;                 // count = 0 or 1
                G2c1: z_pending <= w ? 1'b1 : 1'b0;       // count = 2 if w
                G2c2: z_pending <= w ? 1'b0 : 1'b1;       // count = 2 if ~w
                default: z_pending <= 1'b0;
            endcase
        end
    end

    always @(*) begin
        z = z_pending;
    end

endmodule
