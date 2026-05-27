module TopModule (
    input  a,
    input  b,
    input  c,
    output out
);

    // K-map: out = 0 only at (a=0,b=0,c=0); otherwise 1  ->  out = a | b | c
    assign out = a | b | c;

endmodule
