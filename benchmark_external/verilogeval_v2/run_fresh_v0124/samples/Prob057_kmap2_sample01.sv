module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output reg out
);
    // index = {a,b,c,d}; minterms where out=1 from the K-map
    always @(*) begin
        case ({a, b, c, d})
            4'd0:  out = 1'b1;
            4'd1:  out = 1'b1;
            4'd2:  out = 1'b1;
            4'd4:  out = 1'b1;
            4'd6:  out = 1'b1;
            4'd7:  out = 1'b1;
            4'd8:  out = 1'b1;
            4'd9:  out = 1'b1;
            4'd11: out = 1'b1;
            4'd15: out = 1'b1;
            default: out = 1'b0;
        endcase
    end
endmodule
