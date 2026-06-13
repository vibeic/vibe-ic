module TopModule (
    input              clk,
    input              load,
    input      [511:0] data,
    output reg [511:0] q
);

    // Left neighbour of cell i is q[i+1]; Right neighbour is q[i-1].
    // Boundaries q[512] and q[-1] are 0.
    wire [511:0] left  = {1'b0, q[511:1]};   // left[i]  = q[i+1]
    wire [511:0] right = {q[510:0], 1'b0};   // right[i] = q[i-1]

    wire [511:0] nxt = (q & ~left) | (q & ~right) | (~q & right);

    always @(posedge clk) begin
        if (load)
            q <= data;
        else
            q <= nxt;
    end

endmodule
