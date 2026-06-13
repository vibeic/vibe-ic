module TopModule (
    input              clk,
    input              load,
    input      [511:0] data,
    output reg [511:0] q = 512'b0
);
    integer i;
    reg [511:0] next;
    reg left, center, right;

    always @(*) begin
        for (i = 0; i < 512; i = i + 1) begin
            center = q[i];
            left   = (i == 511) ? 1'b0 : q[i+1];   // q[i+1], boundary q[512]=0
            right  = (i == 0)   ? 1'b0 : q[i-1];    // q[i-1], boundary q[-1]=0
            // Rule 110 lookup on {left,center,right}
            case ({left, center, right})
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
