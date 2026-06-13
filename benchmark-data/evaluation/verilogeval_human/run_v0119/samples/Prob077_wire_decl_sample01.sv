module TopModule (
    input a,
    input b,
    input c,
    input d,
    output out,
    output out_n
);
    wire ab, cd;
    assign ab = a & b;
    assign cd = c & d;
    assign out   = ab | cd;
    assign out_n = ~out;
endmodule
