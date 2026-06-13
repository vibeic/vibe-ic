module TopModule (
    input  [3:0] x,
    output reg   f
);

    // K-map: columns = x[0]x[1], rows = x[2]x[3]
    always @(*) begin
        case ({x[2], x[3], x[0], x[1]})
            4'b0000: f = 1'b1; // r00 c00
            4'b0001: f = 1'b0; // r00 c01
            4'b0011: f = 1'b0; // r00 c11
            4'b0010: f = 1'b1; // r00 c10
            4'b0100: f = 1'b0; // r01 c00
            4'b0101: f = 1'b0; // r01 c01
            4'b0111: f = 1'b0; // r01 c11
            4'b0110: f = 1'b0; // r01 c10
            4'b1100: f = 1'b1; // r11 c00
            4'b1101: f = 1'b1; // r11 c01
            4'b1111: f = 1'b1; // r11 c11
            4'b1110: f = 1'b0; // r11 c10
            4'b1000: f = 1'b1; // r10 c00
            4'b1001: f = 1'b1; // r10 c01
            4'b1011: f = 1'b0; // r10 c11
            4'b1010: f = 1'b1; // r10 c10
            default: f = 1'b0;
        endcase
    end

endmodule
