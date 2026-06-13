module TopModule (
    input  [3:0] in,
    output [1:0] pos
);
    reg [1:0] p;
    always @(*) begin
        casez (in)
            4'b???1: p = 2'd0;
            4'b??10: p = 2'd1;
            4'b?100: p = 2'd2;
            4'b1000: p = 2'd3;
            default: p = 2'd0;   // input zero => 0
        endcase
    end
    assign pos = p;
endmodule
