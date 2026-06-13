module TopModule (
    input         clk,
    input         load,
    input         ena,
    input  [1:0]  amount,
    input  [63:0] data,
    output reg [63:0] q
);

    initial q = 64'b0;

    always @(posedge clk) begin
        if (load)
            q <= data;
        else if (ena) begin
            case (amount)
                2'b00: q <= q <<< 1;
                2'b01: q <= q <<< 8;
                2'b10: q <= $signed(q) >>> 1;
                2'b11: q <= $signed(q) >>> 8;
                default: q <= q;
            endcase
        end
    end

endmodule
