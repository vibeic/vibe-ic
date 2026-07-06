// program-SOLVED multiplexer (individual data ports); deterministic.
module TopModule (
    input sel,
    input a,
    input b,
    output reg out
);
    always @(*) begin
        case (sel)
            1'd0: out = a;
            1'd1: out = b;
            default: out = 1'b0;
        endcase
    end
endmodule
