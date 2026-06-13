module JC_counter (
    input            clk,
    input            rst_n,
    output reg [63:0] Q
);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            Q <= 64'b0;
        end else begin
            // Johnson counter: shift right, feed inverted Q[0] into MSB
            // Q[0]==0 -> append 1 at MSB; Q[0]==1 -> append 0 at MSB
            Q <= {~Q[0], Q[63:1]};
        end
    end

endmodule
