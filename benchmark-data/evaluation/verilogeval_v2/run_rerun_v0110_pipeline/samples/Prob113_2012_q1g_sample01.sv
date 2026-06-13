module TopModule (
    input  [3:0] x,
    output reg   f
);
    // Index = {x[0], x[1], x[2], x[3]}; value from K-map
    always @(*) begin
        case ({x[0], x[1], x[2], x[3]})
            4'b0000: f = 1'b1; // x0x1=00, x2x3=00
            4'b0001: f = 1'b0; // x0x1=00, x2x3=01
            4'b0011: f = 1'b1; // x0x1=00, x2x3=11
            4'b0010: f = 1'b1; // x0x1=00, x2x3=10
            4'b0100: f = 1'b0; // x0x1=01, x2x3=00
            4'b0101: f = 1'b0; // x0x1=01, x2x3=01
            4'b0111: f = 1'b1; // x0x1=01, x2x3=11
            4'b0110: f = 1'b1; // x0x1=01, x2x3=10
            4'b1100: f = 1'b0; // x0x1=11, x2x3=00
            4'b1101: f = 1'b0; // x0x1=11, x2x3=01
            4'b1111: f = 1'b1; // x0x1=11, x2x3=11
            4'b1110: f = 1'b0; // x0x1=11, x2x3=10
            4'b1000: f = 1'b1; // x0x1=10, x2x3=00
            4'b1001: f = 1'b0; // x0x1=10, x2x3=01
            4'b1011: f = 1'b0; // x0x1=10, x2x3=11
            4'b1010: f = 1'b1; // x0x1=10, x2x3=10
            default: f = 1'b0;
        endcase
    end
endmodule
