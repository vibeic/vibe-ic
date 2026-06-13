module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output reg out
);
    // Index {a,b,c,d}. Minimized SOP absorbing don't-cares {4,9,d}:
    //   ones {2,3,8,a,b,c,e,f}, zeros {0,1,5,6,7}
    //   out = a | (~b & c)
    always @(*) begin
        out = a | (~b & c);
    end
endmodule
