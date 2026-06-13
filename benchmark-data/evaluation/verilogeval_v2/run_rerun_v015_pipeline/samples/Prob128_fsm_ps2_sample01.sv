module TopModule (
    input  clk,
    input  reset,
    input  [7:0] in,
    output done
);

    localparam SEARCH = 2'd0;  // discard bytes until in[3]==1 (byte 1)
    localparam BYTE2  = 2'd1;  // first byte seen, waiting for 2nd
    localparam BYTE3  = 2'd2;  // waiting for 3rd byte
    localparam DONE   = 2'd3;  // signal done, in this cycle in[] is a new byte 1 candidate

    reg [1:0] state, next;

    always @(*) begin
        case (state)
            SEARCH: next = in[3] ? BYTE2 : SEARCH;
            BYTE2:  next = BYTE3;
            BYTE3:  next = DONE;
            DONE:   next = in[3] ? BYTE2 : SEARCH;
            default: next = SEARCH;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= SEARCH;
        else
            state <= next;
    end

    assign done = (state == DONE);

endmodule
