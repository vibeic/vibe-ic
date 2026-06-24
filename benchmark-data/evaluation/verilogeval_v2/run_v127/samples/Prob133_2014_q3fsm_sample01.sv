module TopModule (
    input  clk,
    input  reset,
    input  s,
    input  w,
    output z
);

    // State A: wait for s=1. Once s=1, begin examining w over back-to-back
    // 3-cycle windows. z asserts in the cycle right after a window in which
    // w=1 in exactly two of the three cycles. Windows are contiguous: the
    // report cycle is simultaneously the first sample of the next window.

    localparam A = 2'd0;   // idle, watching s
    localparam W0 = 2'd1;  // first cycle of a 3-cycle window (also report cycle)
    localparam W1 = 2'd2;  // second cycle of window
    localparam W2 = 2'd3;  // third cycle of window

    reg [1:0] state;
    reg [1:0] ones;        // count of w=1 in current window so far

    reg z_r;
    assign z = z_r;

    always @(posedge clk) begin
        if (reset) begin
            state <= A;
            ones  <= 0;
            z_r   <= 0;
        end else begin
            z_r <= 0;          // default
            case (state)
                A: begin
                    if (s) begin
                        // s=1 this cycle; w is examined starting next cycle.
                        state <= W0;
                        ones  <= 0;
                    end else begin
                        state <= A;
                    end
                end
                W0: begin
                    ones  <= w;            // first sample of window
                    state <= W1;
                end
                W1: begin
                    ones  <= ones + w;     // second sample
                    state <= W2;
                end
                W2: begin
                    // third sample; window complete -> report next cycle (W0)
                    if ((ones + w) == 2'd2)
                        z_r <= 1;
                    state <= W0;
                    ones  <= 0;
                end
                default: state <= A;
            endcase
        end
    end

endmodule
