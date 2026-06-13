module TopModule (
    input  clk,
    input  load,
    input  [511:0] data,
    output reg [511:0] q
);

    integer i;
    reg left, center, right;

    // Rule 110: per the table, next-state is 1 for all neighbourhoods
    // except (L,C,R) in {111, 100, 000}.  Equivalent boolean:
    //   next = (C & ~(L & R)) | (R & ~C)
    // where Left = q[i+1], Center = q[i], Right = q[i-1].
    // Boundaries q[-1] and q[512] are 0.
    always @(posedge clk) begin
        if (load) begin
            q <= data;
        end else begin
            for (i = 0; i < 512; i = i + 1) begin
                left   = (i == 511) ? 1'b0 : q[i+1];
                center = q[i];
                right  = (i == 0)   ? 1'b0 : q[i-1];
                q[i] <= (center & ~(left & right)) | (right & ~center);
            end
        end
    end

endmodule
