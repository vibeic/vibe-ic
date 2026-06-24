// program-SOLVED serial framing receiver (start/N-data/stop); deterministic, no AI.
module TopModule(
    input clk,
    input reset,
    input in,
    output done
);
    localparam [3:0] IDLE=4'd0, D0=4'd1, D1=4'd2, D2=4'd3, D3=4'd4, D4=4'd5, D5=4'd6, D6=4'd7, D7=4'd8, STOP=4'd9, DONE=4'd10, ERR=4'd11;
    reg [3:0] state, nstate;
    always @(*) begin
        case (state)
            IDLE: nstate = in ? IDLE : D0;
            D0: nstate = D1;
            D1: nstate = D2;
            D2: nstate = D3;
            D3: nstate = D4;
            D4: nstate = D5;
            D5: nstate = D6;
            D6: nstate = D7;
            D7: nstate = STOP;
            STOP: nstate = in ? DONE : ERR;
            DONE: nstate = in ? IDLE : D0;
            ERR:  nstate = in ? IDLE : ERR;
            default: nstate = IDLE;
        endcase
    end
    always @(posedge clk) begin
        if (reset) state <= IDLE;
        else state <= nstate;
    end
    assign done = (state == DONE);
endmodule
