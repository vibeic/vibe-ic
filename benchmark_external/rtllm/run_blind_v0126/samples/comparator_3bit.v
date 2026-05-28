module comparator_3bit (
    input  [2:0] A,
    input  [2:0] B,
    output       A_greater,
    output       A_equal,
    output       A_less
);
    assign A_greater = (A > B);
    assign A_equal   = (A == B);
    assign A_less    = (A < B);
endmodule
