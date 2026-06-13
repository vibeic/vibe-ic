module TopModule (
    input  a,
    input  b,
    input  c,
    output out
);

    // K-map: only minterm a=0,bc=00 is 0; all others are 1.
    // out = 0 only when a=0 & b=0 & c=0 -> out = a | b | c
    assign out = a | b | c;

endmodule
