// fibonacci_series
// 32-bit Fibonacci series generator with overflow detection and auto-restart.
//
// Behaviour (per specification):
//   - Starts from F(0)=0, F(1)=1. RegA holds F(n-2), RegB holds F(n-1).
//   - Each rising clock edge: next_fib = RegA + RegB (33-bit sum to expose carry).
//   - Normal advance: RegA<=RegB, RegB<=next_fib, fib_out<=next_fib.
//   - Overflow detect (next_fib[32]==1): set overflow_detected, hold the last
//     valid Fibonacci value (RegB) on fib_out; overflow_flag stays 0 this cycle.
//   - One cycle later (overflow_detected==1): assert overflow_flag, reset fib_out
//     to 0 and restart the sequence (RegA=0, RegB=1); clear overflow_detected.
//   - overflow_flag is thus a one-cycle pulse asserted the cycle after detection,
//     coincident with the automatic restart; it returns low once the sequence
//     resumes normal operation.
//
// Reset (rst, active-high, synchronous): RegA=0, RegB=1, fib_out=0,
//   overflow_flag=0, overflow_detected=0.

module fibonacci_series (
    input  wire        clk,
    input  wire        rst,
    output reg  [31:0] fib_out,
    output reg         overflow_flag
);

    reg [31:0] RegA;              // F(n-2)
    reg [31:0] RegB;              // F(n-1)
    reg        overflow_detected; // internal: overflow seen, restart pending

    // 33-bit sum so bit [32] is the overflow (carry-out) of the 32-bit addition.
    wire [32:0] next_fib = {1'b0, RegA} + {1'b0, RegB};

    always @(posedge clk) begin
        if (rst) begin
            RegA              <= 32'd0;
            RegB              <= 32'd1;
            fib_out           <= 32'd0;
            overflow_flag     <= 1'b0;
            overflow_detected <= 1'b0;
        end else if (overflow_detected) begin
            // One cycle after overflow: assert the flag and restart the series.
            RegA              <= 32'd0;
            RegB              <= 32'd1;
            fib_out           <= 32'd0;
            overflow_flag     <= 1'b1;
            overflow_detected <= 1'b0;
        end else if (next_fib[32]) begin
            // Overflow this cycle: hold the last valid Fibonacci value, arm flag.
            overflow_detected <= 1'b1;
            fib_out           <= RegB;
            overflow_flag     <= 1'b0;
        end else begin
            // Normal Fibonacci advance.
            RegA              <= RegB;
            RegB              <= next_fib[31:0];
            fib_out           <= next_fib[31:0];
            overflow_flag     <= 1'b0;
        end
    end

endmodule
