module TopModule (
    input  a,
    input  b,
    input  c,
    output out
);
    // KMap: out=0 only when a=0,b=0,c=0; else out=1
    assign out = a | b | c;
endmodule
