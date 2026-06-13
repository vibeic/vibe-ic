module TopModule (
    input  a,
    input  b,
    input  c,
    output out
);

    // KMap: out=1 everywhere except (a=0, bc=00)
    // out = a | b | c
    assign out = a | b | c;

endmodule
