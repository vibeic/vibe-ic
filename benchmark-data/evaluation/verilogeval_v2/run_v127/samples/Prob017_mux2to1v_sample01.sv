// program-SOLVED multiplexer (individual data ports); deterministic.
module TopModule (
    input sel,
    input [99:0] a,
    input [99:0] b,
    output reg [99:0] out
);
    always @(*) begin
        case (sel)
            1'd0: out = a;
            1'd1: out = b;
            default: out = 100'b0;
        endcase
    end
endmodule
