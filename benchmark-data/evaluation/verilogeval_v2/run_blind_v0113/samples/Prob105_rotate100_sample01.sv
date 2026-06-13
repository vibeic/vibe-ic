module TopModule (
    input         clk,
    input         load,
    input  [1:0]  ena,
    input  [99:0] data,
    output reg [99:0] q = 100'b0
);
    always @(posedge clk) begin
        if (load)
            q <= data;
        else begin
            case (ena)
                2'b01: q <= {q[0], q[99:1]};   // rotate right by 1
                2'b10: q <= {q[98:0], q[99]};  // rotate left by 1
                default: q <= q;               // no rotate
            endcase
        end
    end
endmodule
