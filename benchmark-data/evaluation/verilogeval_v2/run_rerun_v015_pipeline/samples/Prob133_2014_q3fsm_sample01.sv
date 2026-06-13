module TopModule (
    input  clk,
    input  reset,
    input  s,
    input  w,
    output z
);

    // States:
    //  A          : wait for s==1
    //  After s, examine w for three consecutive cycles, counting w==1.
    //  We track (which of the 3 reads, count so far).
    //  reads happen on entry to the counting states.
    localparam A   = 4'd0;
    // c<n>_<k>: about to take read number n (1..3 done), with k ones seen so far
    localparam S1     = 4'd1;  // first read upcoming (count starts at 0)
    localparam S2_0   = 4'd2;  // second read upcoming, 0 ones so far
    localparam S2_1   = 4'd3;  // second read upcoming, 1 one so far
    localparam S3_0   = 4'd4;  // third read upcoming, 0 ones
    localparam S3_1   = 4'd5;  // third read upcoming, 1 one
    localparam S3_2   = 4'd6;  // third read upcoming, 2 ones
    // After 3rd read: output z=(total==2) in this state, and begin new window
    localparam Z0     = 4'd7;  // total != 2 -> z=0, new window's 1st read upcoming
    localparam Z1     = 4'd8;  // total == 2 -> z=1, new window's 1st read upcoming

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            A:    next = s ? S1 : A;
            // first read: w consumed now
            S1:   next = w ? S2_1 : S2_0;
            // second read
            S2_0: next = w ? S3_1 : S3_0;
            S2_1: next = w ? S3_2 : S3_1;
            // third read -> decide
            S3_0: next = w ? Z0 : Z0;  // total 0 or 1 -> not 2
            S3_1: next = w ? Z1 : Z0;  // 1 + w : total 2 if w else 1
            S3_2: next = w ? Z0 : Z1;  // 2 + w : total 3 (no) or 2 (yes)
            // output cycle; immediately begin next window's first read
            Z0:   next = w ? S2_1 : S2_0;
            Z1:   next = w ? S2_1 : S2_0;
            default: next = A;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= A;
        else
            state <= next;
    end

    assign z = (state == Z1);

endmodule
