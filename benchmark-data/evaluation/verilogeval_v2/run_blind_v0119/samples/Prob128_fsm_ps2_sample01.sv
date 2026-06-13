module TopModule(
    input        clk,
    input        reset,
    input  [7:0] in,
    output       done
);
    localparam BYTE1 = 2'd0; // hunting for a byte with in[3]=1
    localparam BYTE2 = 2'd1; // got byte 1, this is byte 2
    localparam BYTE3 = 2'd2; // this is byte 3
    localparam DONE  = 2'd3; // signal done (cycle after 3rd byte)
    reg [1:0] state, next;

    always @(*) begin
        case (state)
            BYTE1: next = in[3] ? BYTE2 : BYTE1;
            BYTE2: next = BYTE3;
            BYTE3: next = DONE;
            DONE:  next = in[3] ? BYTE2 : BYTE1; // start hunting next message
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
