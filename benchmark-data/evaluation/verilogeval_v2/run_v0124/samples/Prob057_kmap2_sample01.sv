module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output reg out
);
    // index = {a,b,c,d}; out=1 minterms from the K-map
    always @(*) begin
        case ({a, b, c, d})
            4'd0:  out = 1'b1; // abcd=0000
            4'd1:  out = 1'b1; // 0001
            4'd2:  out = 1'b1; // 0010
            4'd3:  out = 1'b0; // 0011
            4'd4:  out = 1'b1; // 0100
            4'd5:  out = 1'b0; // 0101
            4'd6:  out = 1'b1; // 0110
            4'd7:  out = 1'b1; // 0111
            4'd8:  out = 1'b1; // 1000
            4'd9:  out = 1'b1; // 1001
            4'd10: out = 1'b0; // 1010
            4'd11: out = 1'b1; // 1011
            4'd12: out = 1'b0; // 1100
            4'd13: out = 1'b0; // 1101
            4'd14: out = 1'b0; // 1110
            4'd15: out = 1'b1; // 1111
            default: out = 1'b0;
        endcase
    end
endmodule
