// JC_counter: 64-bit Johnson (twisted-ring) counter.
// Reset -> 0. Otherwise shift Q right by one (Q[63:1]) and feed a new MSB:
//   - Q[0]==0 -> append 1 at the MSB
//   - Q[0]==1 -> append 0 at the MSB
// This produces the Johnson sequence (e.g. 4-bit: 0000,1000,1100,1110,1111,
// 0111,0011,0001,0000,...).
module JC_counter (
    input             clk,
    input             rst_n,
    output reg [63:0] Q
);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            Q <= 64'd0;
        else if (Q[0] == 1'b0)
            Q <= {1'b1, Q[63:1]};
        else
            Q <= {1'b0, Q[63:1]};
    end

endmodule
