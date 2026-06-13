module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    input  e,
    output [24:0] out
);

    wire [4:0] v = {a, b, c, d, e};

    assign out = {
        ~v[4]^v[4], ~v[4]^v[3], ~v[4]^v[2], ~v[4]^v[1], ~v[4]^v[0],
        ~v[3]^v[4], ~v[3]^v[3], ~v[3]^v[2], ~v[3]^v[1], ~v[3]^v[0],
        ~v[2]^v[4], ~v[2]^v[3], ~v[2]^v[2], ~v[2]^v[1], ~v[2]^v[0],
        ~v[1]^v[4], ~v[1]^v[3], ~v[1]^v[2], ~v[1]^v[1], ~v[1]^v[0],
        ~v[0]^v[4], ~v[0]^v[3], ~v[0]^v[2], ~v[0]^v[1], ~v[0]^v[0]
    };

endmodule
