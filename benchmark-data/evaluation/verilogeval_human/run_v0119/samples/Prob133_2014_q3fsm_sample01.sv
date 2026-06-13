module TopModule (
  input clk,
  input reset,
  input s,
  input w,
  output reg z
);
    // Window of 3 cycles counts w=1 occurrences; z=1 the cycle after a window
    // with exactly two 1s. The z-cycle is also sample-1 of the next window.
    localparam A    = 4'd0,
               S1   = 4'd1,   // sample1, z=0
               S1z  = 4'd2,   // sample1, z=1
               S2_0 = 4'd3,   // sample2, running count 0
               S2_1 = 4'd4,   // sample2, running count 1
               S3_0 = 4'd5,   // sample3, running count 0
               S3_1 = 4'd6,   // sample3, running count 1
               S3_2 = 4'd7;   // sample3, running count 2

    reg [3:0] state;

    always @(posedge clk) begin
        if (reset)
            state <= A;
        else begin
            case (state)
                A:    state <= s ? S1 : A;
                // sample 1: count becomes w
                S1:   state <= w ? S2_1 : S2_0;
                S1z:  state <= w ? S2_1 : S2_0;
                // sample 2: count += w
                S2_0: state <= w ? S3_1 : S3_0;
                S2_1: state <= w ? S3_2 : S3_1;
                // sample 3: final count = count + w; z next iff final==2
                S3_0: state <= S1;                 // final 0 or 1 -> never 2
                S3_1: state <= w ? S1z : S1;       // final 2 iff w=1
                S3_2: state <= w ? S1  : S1z;      // final 2 iff w=0
                default: state <= A;
            endcase
        end
    end

    // Moore output
    always @(*) begin
        z = (state == S1z);
    end
endmodule
