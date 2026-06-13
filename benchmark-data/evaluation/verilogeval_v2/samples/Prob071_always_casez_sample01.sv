module TopModule (
    input  [7:0] in,
    output [2:0] pos
);

    reg [2:0] pos_r;

    always @(*) begin
        casez (in)
            8'bzzzzzzz1: pos_r = 3'd0;
            8'bzzzzzz10: pos_r = 3'd1;
            8'bzzzzz100: pos_r = 3'd2;
            8'bzzzz1000: pos_r = 3'd3;
            8'bzzz10000: pos_r = 3'd4;
            8'bzz100000: pos_r = 3'd5;
            8'bz1000000: pos_r = 3'd6;
            8'b10000000: pos_r = 3'd7;
            default:     pos_r = 3'd0;
        endcase
    end

    assign pos = pos_r;

endmodule
