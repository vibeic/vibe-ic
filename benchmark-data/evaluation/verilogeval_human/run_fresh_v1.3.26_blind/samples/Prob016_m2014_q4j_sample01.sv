// program-SOLVED N-bit unsigned adder (carry in MSB); deterministic.
module TopModule (
    input [3:0] x,
    input [3:0] y,
    output [4:0] sum
);
    assign sum = x + y;
endmodule
