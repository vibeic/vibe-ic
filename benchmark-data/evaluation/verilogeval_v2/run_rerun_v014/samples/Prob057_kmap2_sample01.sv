module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output reg out
);

    // K-map (rows cd, cols ab):
    //          ab=00 01 11 10
    //   cd=00 |  1   1   0   1
    //   cd=01 |  1   0   0   1
    //   cd=11 |  0   1   1   1
    //   cd=10 |  1   1   0   0
    always @(*) begin
        case ({a, b, c, d})
            4'b0000: out = 1'b1; // ab00 cd00
            4'b0001: out = 1'b1; // ab00 cd01
            4'b0011: out = 1'b0; // ab00 cd11
            4'b0010: out = 1'b1; // ab00 cd10
            4'b0100: out = 1'b1; // ab01 cd00
            4'b0101: out = 1'b0; // ab01 cd01
            4'b0111: out = 1'b1; // ab01 cd11
            4'b0110: out = 1'b1; // ab01 cd10
            4'b1100: out = 1'b0; // ab11 cd00
            4'b1101: out = 1'b0; // ab11 cd01
            4'b1111: out = 1'b1; // ab11 cd11
            4'b1110: out = 1'b0; // ab11 cd10
            4'b1000: out = 1'b1; // ab10 cd00
            4'b1001: out = 1'b1; // ab10 cd01
            4'b1011: out = 1'b1; // ab10 cd11
            4'b1010: out = 1'b0; // ab10 cd10
            default: out = 1'b0;
        endcase
    end

endmodule
