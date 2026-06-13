module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    input  e,
    output [24:0] out
);
    wire [4:0] v = {a, b, c, d, e};
    // out[24] compares v[4] (a) with v[4] (a), out[0] compares v[0] (e) with v[0] (e).
    // index = row*5 + col counted down from 24; out bit = ~ (row==col? equal) i.e. XNOR.
    // out[24-(i*5+j)] = ~(v[4-i] ^ v[4-j])
    assign out[24] = ~(v[4] ^ v[4]);
    assign out[23] = ~(v[4] ^ v[3]);
    assign out[22] = ~(v[4] ^ v[2]);
    assign out[21] = ~(v[4] ^ v[1]);
    assign out[20] = ~(v[4] ^ v[0]);
    assign out[19] = ~(v[3] ^ v[4]);
    assign out[18] = ~(v[3] ^ v[3]);
    assign out[17] = ~(v[3] ^ v[2]);
    assign out[16] = ~(v[3] ^ v[1]);
    assign out[15] = ~(v[3] ^ v[0]);
    assign out[14] = ~(v[2] ^ v[4]);
    assign out[13] = ~(v[2] ^ v[3]);
    assign out[12] = ~(v[2] ^ v[2]);
    assign out[11] = ~(v[2] ^ v[1]);
    assign out[10] = ~(v[2] ^ v[0]);
    assign out[9]  = ~(v[1] ^ v[4]);
    assign out[8]  = ~(v[1] ^ v[3]);
    assign out[7]  = ~(v[1] ^ v[2]);
    assign out[6]  = ~(v[1] ^ v[1]);
    assign out[5]  = ~(v[1] ^ v[0]);
    assign out[4]  = ~(v[0] ^ v[4]);
    assign out[3]  = ~(v[0] ^ v[3]);
    assign out[2]  = ~(v[0] ^ v[2]);
    assign out[1]  = ~(v[0] ^ v[1]);
    assign out[0]  = ~(v[0] ^ v[0]);
endmodule
