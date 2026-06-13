module TopModule (
    input  [7:0] a,
    input  [7:0] b,
    input  [7:0] c,
    input  [7:0] d,
    output [7:0] min
);
    wire [7:0] ab  = (a < b)  ? a  : b;
    wire [7:0] cd  = (c < d)  ? c  : d;
    assign min     = (ab < cd) ? ab : cd;
endmodule
