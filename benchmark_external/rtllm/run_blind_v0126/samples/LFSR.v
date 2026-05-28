module LFSR (
    input            clk,
    input            rst,
    output reg [3:0] out
);

    wire feedback;

    // feedback = NOT( out[3] XOR out[2] )
    assign feedback = ~(out[3] ^ out[2]);

    always @(posedge clk) begin
        if (rst) begin
            out <= 4'b0000;
        end else begin
            // shift left, insert feedback at LSB
            out <= {out[2:0], feedback};
        end
    end

endmodule
