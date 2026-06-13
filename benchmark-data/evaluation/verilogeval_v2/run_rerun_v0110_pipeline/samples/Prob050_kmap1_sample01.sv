module TopModule (
    input  a,
    input  b,
    input  c,
    output out
);
    // K-map: out = 0 only when a=0,b=0,c=0; else 1
    assign out = a | b | c;
endmodule
