module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output reg out
);
    // out=1 minterms {a,b,c,d}:
    // 0000 0001 0010 0100 0110 0111 1000 1001 1011 1111
    always @(*) begin
        case ({a, b, c, d})
            4'b0000: out = 1'b1;
            4'b0001: out = 1'b1;
            4'b0010: out = 1'b1;
            4'b0100: out = 1'b1;
            4'b0110: out = 1'b1;
            4'b0111: out = 1'b1;
            4'b1000: out = 1'b1;
            4'b1001: out = 1'b1;
            4'b1011: out = 1'b1;
            4'b1111: out = 1'b1;
            default: out = 1'b0;
        endcase
    end
endmodule
