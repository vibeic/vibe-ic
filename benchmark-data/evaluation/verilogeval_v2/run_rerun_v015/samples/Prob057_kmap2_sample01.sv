module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output out
);

    // KMap rows indexed by cd, columns by ab (00,01,11,10)
    // cd=00: ab=00->1, 01->1, 11->0, 10->1
    // cd=01: ab=00->1, 01->0, 11->0, 10->1
    // cd=11: ab=00->0, 01->1, 11->1, 10->1
    // cd=10: ab=00->1, 01->1, 11->0, 10->0
    reg out_r;
    always @(*) begin
        case ({a, b, c, d})
            4'b0000: out_r = 1'b1; // ab=00 cd=00
            4'b0001: out_r = 1'b1; // ab=00 cd=01
            4'b0011: out_r = 1'b0; // ab=00 cd=11
            4'b0010: out_r = 1'b1; // ab=00 cd=10
            4'b0100: out_r = 1'b1; // ab=01 cd=00
            4'b0101: out_r = 1'b0; // ab=01 cd=01
            4'b0111: out_r = 1'b1; // ab=01 cd=11
            4'b0110: out_r = 1'b1; // ab=01 cd=10
            4'b1100: out_r = 1'b0; // ab=11 cd=00
            4'b1101: out_r = 1'b0; // ab=11 cd=01
            4'b1111: out_r = 1'b1; // ab=11 cd=11
            4'b1110: out_r = 1'b0; // ab=11 cd=10
            4'b1000: out_r = 1'b1; // ab=10 cd=00
            4'b1001: out_r = 1'b1; // ab=10 cd=01
            4'b1011: out_r = 1'b1; // ab=10 cd=11
            4'b1010: out_r = 1'b0; // ab=10 cd=10
            default: out_r = 1'b0;
        endcase
    end

    assign out = out_r;

endmodule
