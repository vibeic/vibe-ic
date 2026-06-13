module TopModule (
    input              clk,
    input              load,
    input      [511:0] data,
    output reg [511:0] q
);

    integer i;
    reg left, center, right;

    always @(posedge clk) begin
        if (load) begin
            q <= data;
        end else begin
            for (i = 0; i < 512; i = i + 1) begin
                left   = (i == 511) ? 1'b0 : q[i+1];
                center = q[i];
                right  = (i == 0)   ? 1'b0 : q[i-1];
                case ({left, center, right})
                    3'b111: q[i] <= 1'b0;
                    3'b110: q[i] <= 1'b1;
                    3'b101: q[i] <= 1'b1;
                    3'b100: q[i] <= 1'b0;
                    3'b011: q[i] <= 1'b1;
                    3'b010: q[i] <= 1'b1;
                    3'b001: q[i] <= 1'b1;
                    3'b000: q[i] <= 1'b0;
                endcase
            end
        end
    end

endmodule
