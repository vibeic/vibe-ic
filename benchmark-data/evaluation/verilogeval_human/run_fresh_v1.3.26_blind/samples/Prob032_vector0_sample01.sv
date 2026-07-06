// program-SOLVED vector op (passthrough + position-mapped bits); deterministic wiring.
module TopModule (
    input [2:0] vec,
    output [2:0] outv,
    output o2,
    output o1,
    output o0
);
    assign outv = vec;
    assign { o2, o1, o0 } = vec;
endmodule
