module TopModule (
    input        clk,
    input        reset,
    input  [7:0] in,
    output       done
);

    localparam BYTE1 = 2'd0,  // searching for first byte (in[3]==1)
               BYTE2 = 2'd1,  // received byte 1, waiting byte 2
               BYTE3 = 2'd2,  // received byte 2, waiting byte 3
               DONE  = 2'd3;  // 3rd byte received last cycle -> assert done

    reg [1:0] state, nxt;

    always @(*) begin
        case (state)
            BYTE1: nxt = in[3] ? BYTE2 : BYTE1;
            BYTE2: nxt = BYTE3;
            BYTE3: nxt = DONE;
            DONE:  nxt = in[3] ? BYTE2 : BYTE1;  // start searching again
            default: nxt = BYTE1;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= BYTE1;
        else
            state <= nxt;
    end

    assign done = (state == DONE);

endmodule
