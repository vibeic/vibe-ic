module TopModule (
    input  [3:0] x,
    output reg f
);
    // K-map: columns = x[0]x[1], rows = x[2]x[3]
    // index built as {x[2],x[3],x[0],x[1]}
    always @(*) begin
        case ({x[2], x[3], x[0], x[1]})
            // row x2x3=00
            4'b00_00: f = 1'b1;
            4'b00_01: f = 1'b0;
            4'b00_11: f = 1'b0;
            4'b00_10: f = 1'b1;
            // row x2x3=01
            4'b01_00: f = 1'b0;
            4'b01_01: f = 1'b0;
            4'b01_11: f = 1'b0;
            4'b01_10: f = 1'b0;
            // row x2x3=11
            4'b11_00: f = 1'b1;
            4'b11_01: f = 1'b1;
            4'b11_11: f = 1'b1;
            4'b11_10: f = 1'b0;
            // row x2x3=10
            4'b10_00: f = 1'b1;
            4'b10_01: f = 1'b1;
            4'b10_11: f = 1'b0;
            4'b10_10: f = 1'b1;
            default:  f = 1'b0;
        endcase
    end
endmodule
