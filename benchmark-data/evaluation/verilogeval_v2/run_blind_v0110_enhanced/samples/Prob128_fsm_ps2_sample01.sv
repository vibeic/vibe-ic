module TopModule(
    input        clk,
    input        reset,
    input  [7:0] in,
    output       done
);
    localparam BYTE1 = 2'd0,
               BYTE2 = 2'd1,
               BYTE3 = 2'd2,
               DONE  = 2'd3;

    reg [1:0] state, next;

    always @(*) begin
        case (state)
            BYTE1: next = in[3] ? BYTE2 : BYTE1;
            BYTE2: next = BYTE3;
            BYTE3: next = DONE;
            DONE:  next = in[3] ? BYTE2 : BYTE1;
            default: next = BYTE1;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= BYTE1;
        else
            state <= next;
    end

    assign done = (state == DONE);
endmodule
