module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output reg out
);
    // SPEC DEFECT: prompt gives only 3 concrete truth-table points
    //   {a,b,c,d}=0000 -> 0 ; 1111 -> 1 ; 0101 -> 0
    // and otherwise says "same output for any combination" (non-informative).
    // The full K-map is NOT recoverable from the prompt. Implemented a
    // function consistent with all 3 stated points.
    always @(*) begin
        out = a & d;
    end
endmodule
