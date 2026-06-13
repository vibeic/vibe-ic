module TopModule (
    input        clk,
    input        reset,
    input  [7:0] in,
    output       done
);
    // BYTE1: searching for a byte with in[3]=1 (first byte of message)
    // BYTE2/BYTE3: counting the 2nd and 3rd bytes
    // DONE: pulse done for one cycle, simultaneously inspect the next byte
    localparam BYTE1 = 2'd0, BYTE2 = 2'd1, BYTE3 = 2'd2, DONE = 2'd3;
    reg [1:0] state, nstate;

    always @(*) begin
        case (state)
            BYTE1: nstate = in[3] ? BYTE2 : BYTE1;
            BYTE2: nstate = BYTE3;
            BYTE3: nstate = DONE;
            DONE:  nstate = in[3] ? BYTE2 : BYTE1; // next message search
            default: nstate = BYTE1;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= BYTE1;
        else
            state <= nstate;
    end

    // Moore output: done high only in DONE state.
    assign done = (state == DONE);
endmodule
