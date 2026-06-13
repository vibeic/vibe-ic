module TopModule (
    input  x3,
    input  x2,
    input  x1,
    output f
);

    // f=1 for: 010,011,101,111  (x3 x2 x1)
    assign f = (~x3 & x2 & ~x1) |
               (~x3 & x2 &  x1) |
               ( x3 & ~x2 & x1) |
               ( x3 &  x2 & x1);

endmodule
