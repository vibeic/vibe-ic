module TopModule (
    input  [3:0] x,
    output       f
);
    // Minimal SOP from K-map (x[0],x[1] cols; x[2],x[3] rows):
    //   f = ~x1·~x3 + ~x0·x2 + x1·x2·x3
    assign f = (~x[1] & ~x[3]) | (~x[0] & x[2]) | (x[1] & x[2] & x[3]);
endmodule
