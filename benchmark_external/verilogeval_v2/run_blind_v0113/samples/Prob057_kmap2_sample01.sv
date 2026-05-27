module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output out
);
    // Direct truth-table encoding from the K-map (columns=ab, rows=cd).
    reg r;
    always @(*) begin
        case ({a, b, c, d})
            4'b0000: r = 1'b1;
            4'b0001: r = 1'b1;
            4'b0010: r = 1'b1;
            4'b0011: r = 1'b0;
            4'b0100: r = 1'b1;
            4'b0101: r = 1'b0;
            4'b0110: r = 1'b1;
            4'b0111: r = 1'b1;
            4'b1000: r = 1'b1;
            4'b1001: r = 1'b1;
            4'b1010: r = 1'b0;
            4'b1011: r = 1'b1;
            4'b1100: r = 1'b0;
            4'b1101: r = 1'b0;
            4'b1110: r = 1'b0;
            4'b1111: r = 1'b1;
            default: r = 1'b0;
        endcase
    end
    assign out = r;
endmodule
