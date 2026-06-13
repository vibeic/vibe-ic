module TopModule (
    input  clk,
    input  load,
    input  [511:0] data,
    output reg [511:0] q
);
    integer i;
    reg [511:0] nq;
    reg left, center, right;

    always @(posedge clk) begin
        if (load)
            q <= data;
        else begin
            for (i = 0; i < 512; i = i + 1) begin
                center = q[i];
                left   = (i == 511) ? 1'b0 : q[i+1];
                right  = (i == 0)   ? 1'b0 : q[i-1];
                // Rule 110: next is 0 only for 111 and 000
                nq[i] = ~((left & center & right) | (~left & ~center & ~right));
            end
            q <= nq;
        end
    end
endmodule
