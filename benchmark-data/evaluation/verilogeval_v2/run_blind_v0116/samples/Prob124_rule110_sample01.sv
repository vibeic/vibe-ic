module TopModule (
    input              clk,
    input              load,
    input      [511:0] data,
    output reg [511:0] q = 512'b0
);
    integer i;
    reg left, center, right;

    always @(posedge clk) begin
        if (load) begin
            q <= data;
        end else begin
            for (i = 0; i < 512; i = i + 1) begin
                center = q[i];
                left   = (i == 511) ? 1'b0 : q[i+1];
                right  = (i == 0)   ? 1'b0 : q[i-1];
                // Rule 110: next=1 for LCR in {110,101,011,010,001}
                q[i] <= (left & center & ~right)  |
                        (left & ~center & right)  |
                        (~left & center & right)  |
                        (~left & center & ~right) |
                        (~left & ~center & right);
            end
        end
    end
endmodule
