module TopModule (
    input        clk,
    input        reset,
    input  [7:0] in,
    output       done
);

    // S0: waiting for byte1 (in[3] marks the first byte of a message)
    // S1: byte1 accepted, this cycle's `in` is byte2
    // S2: byte2 accepted, this cycle's `in` is byte3
    // S3: byte3 was accepted last cycle -> done asserted this cycle;
    //     this cycle's `in` may already be byte1 of the next message
    localparam S0 = 2'd0,
               S1 = 2'd1,
               S2 = 2'd2,
               S3 = 2'd3;

    reg [1:0] state, next_state;

    always @(*) begin
        case (state)
            S0: next_state = in[3] ? S1 : S0;
            S1: next_state = S2;
            S2: next_state = S3;
            S3: next_state = in[3] ? S1 : S0;
            default: next_state = S0;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= S0;
        else
            state <= next_state;
    end

    assign done = (state == S3);

endmodule
