// program-SOLVED priority encoder (LSB-first, zero default); deterministic.
module TopModule (
    input [3:0] in,
    output reg [1:0] pos
);
    always @(*) begin
        casez (in)
            default    : pos = 2'h0;
            4'bzzz1: pos = 2'd0;
            4'bzz1z: pos = 2'd1;
            4'bz1zz: pos = 2'd2;
            4'b1zzz: pos = 2'd3;
        endcase
    end
endmodule
