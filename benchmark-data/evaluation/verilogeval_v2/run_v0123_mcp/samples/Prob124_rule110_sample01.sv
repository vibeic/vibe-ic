module TopModule (
    input          clk,
    input          load,
    input  [511:0] data,
    output reg [511:0] q
);

    integer i;
    reg L, C, R;
    reg [511:0] nq;

    always @(*) begin
        for (i = 0; i < 512; i = i + 1) begin
            C = q[i];
            L = (i == 511) ? 1'b0 : q[i+1];
            R = (i == 0)   ? 1'b0 : q[i-1];
            // Rule 110: next is 0 only for 111, 100, 000
            nq[i] = ~((L & C & R) | (L & ~C & ~R) | (~L & ~C & ~R));
        end
    end

    always @(posedge clk) begin
        if (load)
            q <= data;
        else
            q <= nq;
    end

endmodule
