// program-SOLVED combinational state-transition + output logic; deterministic.
module TopModule(
    input in,
    input [3:0] state,
    output reg [3:0] next_state,
    output reg out
);
    always @(*) begin
        next_state = 4'd0; out = 1'b0;
        case (state)
            4'd1: begin next_state = in ? 4'd2 : 4'd1; out = 1'b0; end
            4'd2: begin next_state = in ? 4'd2 : 4'd4; out = 1'b0; end
            4'd4: begin next_state = in ? 4'd8 : 4'd1; out = 1'b0; end
            4'd8: begin next_state = in ? 4'd2 : 4'd4; out = 1'b1; end
            default: begin next_state = 4'd0; out = 1'b0; end
        endcase
    end
endmodule
