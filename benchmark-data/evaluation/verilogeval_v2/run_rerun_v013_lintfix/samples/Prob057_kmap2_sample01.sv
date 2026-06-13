module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output reg out
);

    // K-map (rows cd, cols ab in Gray order 00,01,11,10):
    //         ab=00 01 11 10
    //  cd=00 :  1   1  0  1
    //  cd=01 :  1   0  0  1
    //  cd=11 :  0   1  1  1
    //  cd=10 :  1   1  0  0
    // Sum-of-products over the index {a,b,c,d}:
    // minterms where out=1:
    //  abcd: 0000,0100,1000  (cd00: ab=00,01,10)
    //  abcd: 0001,1001       (cd01: ab=00,10)
    //  abcd: 0111,1111,1011  (cd11: ab=01,11,10)
    //  abcd: 0010,0110       (cd10: ab=00,01)
    wire [3:0] in = {a, b, c, d};
    always @(*) begin
        case (in)
            4'b0000: out = 1'b1;
            4'b0100: out = 1'b1;
            4'b1000: out = 1'b1;
            4'b0001: out = 1'b1;
            4'b1001: out = 1'b1;
            4'b0111: out = 1'b1;
            4'b1111: out = 1'b1;
            4'b1011: out = 1'b1;
            4'b0010: out = 1'b1;
            4'b0110: out = 1'b1;
            default: out = 1'b0;
        endcase
    end

endmodule
