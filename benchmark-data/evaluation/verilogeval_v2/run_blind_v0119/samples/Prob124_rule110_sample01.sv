module TopModule(
    input              clk,
    input              load,
    input      [511:0] data,
    output reg [511:0] q = 512'b0
);
    // Rule 110: next[i] depends on Left=q[i+1], Center=q[i], Right=q[i-1].
    // Rule number 110 (01101110): next is 0 only for 111 and 100 and 000.
    //   next = ~(L & C & R) & (C | R)
    // Boundaries: q[-1] and q[512] are 0.
    integer i;
    reg L, C, R;
    always @(posedge clk) begin
        if (load) begin
            q <= data;
        end else begin
            for (i = 0; i < 512; i = i + 1) begin
                C = q[i];
                L = (i == 511) ? 1'b0 : q[i+1];
                R = (i == 0)   ? 1'b0 : q[i-1];
                q[i] <= ~(L & C & R) & (C | R);
            end
        end
    end
endmodule
