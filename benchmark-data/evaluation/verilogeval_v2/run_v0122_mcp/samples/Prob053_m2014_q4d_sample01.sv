module TopModule (
    input  clk,
    input  in,
    output reg out  // reset-less registered output (no reset per spec)
);


    // D = in XOR out, positive edge, no reset.
    always @(posedge clk) begin
        out <= in ^ out;
    end

endmodule
