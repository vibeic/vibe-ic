module TopModule (
    input  clk,
    input  load,
    input  [511:0] data,
    output reg [511:0] q
);

    // Neighbours: left = q[i+1], right = q[i-1]; boundaries shift in 0.
    wire [511:0] left  = {1'b0, q[511:1]};
    wire [511:0] right = {q[510:0], 1'b0};

    // Rule 110: next = (C&~L) | (R&~C) | (C&~R)
    wire [511:0] next = (q & ~left) | (right & ~q) | (q & ~right);

    // Deterministic power-up (no reset port; testbench loads before sampling).
    initial q = 512'b0;

    always @(posedge clk) begin
        if (load)
            q <= data;
        else
            q <= next;
    end

endmodule
