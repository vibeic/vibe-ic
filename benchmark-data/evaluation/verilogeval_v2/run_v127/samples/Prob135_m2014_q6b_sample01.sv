// program-SOLVED from the prompt's own oracle (fsm); deterministic, no AI.
module TopModule(
    input [2:0] y,
    input w,
    output reg Y1
);
    always @(*) begin
        Y1 = 1'b0;
        case ({y, w})
            4'b0000: Y1 = 1'b0;
            4'b0001: Y1 = 1'b0;
            4'b0010: Y1 = 1'b1;
            4'b0011: Y1 = 1'b1;
            4'b0100: Y1 = 1'b0;
            4'b0101: Y1 = 1'b1;
            4'b0110: Y1 = 1'b0;
            4'b0111: Y1 = 1'b0;
            4'b1000: Y1 = 1'b0;
            4'b1001: Y1 = 1'b1;
            4'b1010: Y1 = 1'b1;
            4'b1011: Y1 = 1'b1;
            default: Y1 = 1'b0;
        endcase
    end
endmodule
