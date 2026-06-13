module TopModule(
    input  x,
    input  y,
    output z
);
    // z = 1 when x == y  =>  XNOR
    assign z = ~(x ^ y);
endmodule
