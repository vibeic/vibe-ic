module TopModule (
    input        a,
    input        b,
    input        c,
    output       out
);
    // K-map: the only 0-cell is a=0,b=0,c=0. Minimal SOP:
    assign out = a | b | c;
endmodule
