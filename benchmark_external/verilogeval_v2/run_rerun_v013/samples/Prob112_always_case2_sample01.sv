module TopModule (
    input  [3:0] in,
    output reg [1:0] pos
);

    always @(*) begin
        casez (in)
            4'b???1: pos = 2'd0;
            4'b??10: pos = 2'd1;
            4'b?100: pos = 2'd2;
            4'b1000: pos = 2'd3;
            default: pos = 2'd0;
        endcase
    end

endmodule
