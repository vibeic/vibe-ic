module TopModule (
    input         clk,
    input         load,
    input  [511:0] data,
    output reg [511:0] q = 0
);
    // Rule 90: next[i] = q[i-1] ^ q[i+1], boundaries are 0.
    // {q[510:0],1'b0}  places left neighbour (q[i-1]) at position i (q[-1]=0)
    // {1'b0,q[511:1]}  places right neighbour (q[i+1]) at position i (q[512]=0)
    always @(posedge clk) begin
        if (load)
            q <= data;
        else
            q <= {q[510:0], 1'b0} ^ {1'b0, q[511:1]};
    end
endmodule
