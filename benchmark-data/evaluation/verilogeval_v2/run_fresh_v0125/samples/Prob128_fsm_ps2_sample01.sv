module TopModule (
    input        clk,
    input        reset,
    input  [7:0] in,
    output       done
);

    localparam S_BYTE1 = 2'd0,
               S_BYTE2 = 2'd1,
               S_BYTE3 = 2'd2,
               S_DONE  = 2'd3;

    reg [1:0] state, next;

    always @(*) begin
        case (state)
            S_BYTE1: next = in[3] ? S_BYTE2 : S_BYTE1;
            S_BYTE2: next = S_BYTE3;
            S_BYTE3: next = S_DONE;
            S_DONE:  next = in[3] ? S_BYTE2 : S_BYTE1;
            default: next = S_BYTE1;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= S_BYTE1;
        else
            state <= next;
    end

    assign done = (state == S_DONE);

endmodule
