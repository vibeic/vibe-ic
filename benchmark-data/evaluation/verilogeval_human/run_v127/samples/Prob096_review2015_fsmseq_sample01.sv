// program-SOLVED Moore-LATCHED sequence detector (KMP prefix automaton;
// free internal encoding); deterministic, no AI.
module TopModule(
    input clk,
    input reset,
    input data,
    output start_shifting
);
    localparam [2:0] ACCEPT = 3'd4;
    reg [2:0] state, nstate;
    always @(*) begin
        case (state)
            3'd0: nstate = data ? 3'd1 : 3'd0;
            3'd1: nstate = data ? 3'd2 : 3'd0;
            3'd2: nstate = data ? 3'd2 : 3'd3;
            3'd3: nstate = data ? 3'd4 : 3'd0;
            3'd4: nstate = data ? 3'd4 : 3'd4;
            default: nstate = 3'd0;
        endcase
    end
    always @(posedge clk) begin
        if (reset) state <= 3'd0;
        else state <= nstate;
    end
    assign start_shifting = (state == ACCEPT);
endmodule
