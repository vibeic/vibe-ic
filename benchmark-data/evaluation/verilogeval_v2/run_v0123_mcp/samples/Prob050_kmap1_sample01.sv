module TopModule (
    input  a,
    input  b,
    input  c,
    output out
);
    // K-map: out=0 only at (a,b,c)=(0,0,0); 1 everywhere else
    assign out = a | b | c;
endmodule
