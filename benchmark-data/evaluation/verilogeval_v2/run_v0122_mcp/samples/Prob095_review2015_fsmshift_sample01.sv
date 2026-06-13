module TopModule (
    input  clk,
    input  reset,
    output shift_ena
);

    // Moore FSM: assert shift_ena for 4 cycles after reset, then 0 forever.
    localparam S0 = 3'd0, S1 = 3'd1, S2 = 3'd2, S3 = 3'd3, DONE = 3'd4;
    reg [2:0] state;

    always @(posedge clk) begin
        if (reset)
            state <= S0;
        else begin
            case (state)
                S0:      state <= S1;
                S1:      state <= S2;
                S2:      state <= S3;
                S3:      state <= DONE;
                DONE:    state <= DONE;
                default: state <= DONE;
            endcase
        end
    end

    assign shift_ena = (state == S0) || (state == S1) ||
                       (state == S2) || (state == S3);

endmodule
