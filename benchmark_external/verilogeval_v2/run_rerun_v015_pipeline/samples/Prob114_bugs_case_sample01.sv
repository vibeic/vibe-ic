module TopModule (
    input  [7:0] code,
    output [3:0] out,
    output       valid
);
    reg [3:0] o;
    reg       v;
    always @(*) begin
        o = 4'd0;
        v = 1'b1;
        case (code)
            8'h45: o = 4'd0;
            8'h16: o = 4'd1;
            8'h1e: o = 4'd2;
            8'h26: o = 4'd3;
            8'h25: o = 4'd4;
            8'h2e: o = 4'd5;
            8'h36: o = 4'd6;
            8'h3d: o = 4'd7;
            8'h3e: o = 4'd8;
            8'h46: o = 4'd9;
            default: begin o = 4'd0; v = 1'b0; end
        endcase
    end
    assign out   = o;
    assign valid = v;
endmodule
