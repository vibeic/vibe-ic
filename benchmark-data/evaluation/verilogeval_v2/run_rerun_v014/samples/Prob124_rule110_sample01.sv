module TopModule (
    input          clk,
    input          load,
    input  [511:0] data,
    output reg [511:0] q
);

    integer i;
    reg [511:0] next;
    reg l, c, r;

    always @(*) begin
        for (i = 0; i < 512; i = i + 1) begin
            // left = q[i+1], center = q[i], right = q[i-1]
            // boundaries are zero
            l = (i == 511) ? 1'b0 : q[i+1];
            c = q[i];
            r = (i == 0)   ? 1'b0 : q[i-1];
            // Rule 110: {l,c,r} -> next
            case ({l, c, r})
                3'b111: next[i] = 1'b0;
                3'b110: next[i] = 1'b1;
                3'b101: next[i] = 1'b1;
                3'b100: next[i] = 1'b0;
                3'b011: next[i] = 1'b1;
                3'b010: next[i] = 1'b1;
                3'b001: next[i] = 1'b1;
                3'b000: next[i] = 1'b0;
                default: next[i] = 1'b0;
            endcase
        end
    end

    always @(posedge clk) begin
        if (load)
            q <= data;
        else
            q <= next;
    end

endmodule
