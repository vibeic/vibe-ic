// program-SOLVED combinational state-transition + output logic; deterministic.
module TopModule(
    input in,
    input [1:0] state,
    output reg [1:0] next_state,
    output reg out
);
    always @(*) begin
        next_state = 2'd0; out = 1'b0;
        case (state)
            2'd0: begin next_state = in ? 2'd1 : 2'd0; out = 1'b0; end
            2'd1: begin next_state = in ? 2'd1 : 2'd2; out = 1'b0; end
            2'd2: begin next_state = in ? 2'd3 : 2'd0; out = 1'b0; end
            2'd3: begin next_state = in ? 2'd1 : 2'd2; out = 1'b1; end
            default: begin next_state = 2'd0; out = 1'b0; end
        endcase
    end
endmodule
