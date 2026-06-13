module TopModule (
    input  [7:0] in,
    output [2:0] pos
);
    reg [2:0] pos_r;
    always @(*) begin
        casez (in)
            8'bzzzzzzz1: pos_r = 3'd0;
            8'bzzzzzz1z: pos_r = 3'd1;
            8'bzzzzz1zz: pos_r = 3'd2;
            8'bzzzz1zzz: pos_r = 3'd3;
            8'bzzz1zzzz: pos_r = 3'd4;
            8'bzz1zzzzz: pos_r = 3'd5;
            8'bz1zzzzzz: pos_r = 3'd6;
            8'b1zzzzzzz: pos_r = 3'd7;
            default:     pos_r = 3'd0;
        endcase
    end
    assign pos = pos_r;
endmodule
