module TopModule (
    input  wire [3:0] x,
    output wire       f
);
    // K-map labels x[1..4] map to declared bits x[3..0] (x[1]=MSB).
    // f = (~x[3] & x[1]) | (x[2] & x[0])
    assign f = (~x[3] & x[1]) | (x[2] & x[0]);
endmodule
