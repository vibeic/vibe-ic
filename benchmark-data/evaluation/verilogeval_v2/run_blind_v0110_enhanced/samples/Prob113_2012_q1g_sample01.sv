module TopModule (
    input  wire [3:0] x,
    output reg        f
);
    always @(*) begin
        case (x)
            4'd0, 4'd1, 4'd4, 4'd5, 4'd6, 4'd12, 4'd14, 4'd15: f = 1'b1;
            default: f = 1'b0;
        endcase
    end
endmodule
