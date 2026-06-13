module TopModule (
    input  [3:0] x,
    output reg f
);

    // f=1 for x in {0000,0001,0100,0101,0110,1100,1110,1111}, else 0
    always @(*) begin
        case (x)
            4'b0000: f = 1'b1;
            4'b0001: f = 1'b1;
            4'b0100: f = 1'b1;
            4'b0101: f = 1'b1;
            4'b0110: f = 1'b1;
            4'b1100: f = 1'b1;
            4'b1110: f = 1'b1;
            4'b1111: f = 1'b1;
            default: f = 1'b0;
        endcase
    end

endmodule
