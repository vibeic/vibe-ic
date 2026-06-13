module TopModule (
    input  [3:0] x,
    output       f
);
    // Map prompt names x1..x4 to x[3:0] (x1=MSB=x[3] ... x4=LSB=x[0])
    // f = (x3 & ~x1) | (x1 & x2 & ~x3)
    wire x1 = x[3];
    wire x2 = x[2];
    wire x3 = x[1];
    assign f = (x3 & ~x1) | (x1 & x2 & ~x3);
endmodule
