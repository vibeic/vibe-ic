module TopModule (
    input  clk,
    input  load,
    input  [511:0] data,
    output reg [511:0] q
);
    integer i;
    reg [511:0] nq;
    reg l, c, r;

    always @(posedge clk) begin
        if (load) begin
            q <= data;
        end else begin
            for (i = 0; i < 512; i = i + 1) begin
                c = q[i];
                // Per the prompt's table, Left is q[i+1], Right is q[i-1].
                // Boundaries q[512] and q[-1] are 0.
                l = (i == 511) ? 1'b0 : q[i+1];
                r = (i == 0)   ? 1'b0 : q[i-1];
                // Rule 110 next-state truth table on {l,c,r}:
                // 111->0 110->1 101->1 100->0 011->1 010->1 001->1 000->0
                case ({l, c, r})
                    3'b111: nq[i] = 1'b0;
                    3'b110: nq[i] = 1'b1;
                    3'b101: nq[i] = 1'b1;
                    3'b100: nq[i] = 1'b0;
                    3'b011: nq[i] = 1'b1;
                    3'b010: nq[i] = 1'b1;
                    3'b001: nq[i] = 1'b1;
                    3'b000: nq[i] = 1'b0;
                endcase
            end
            q <= nq;
        end
    end
endmodule
