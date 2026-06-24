module TopModule (
    input         clk,
    input         reset,
    input  [7:0]  in,
    output [23:0] out_bytes,
    output        done
);

    // Discard bytes until one has in[3]=1 (that is byte 1 of a message); then
    // collect bytes 2 and 3. done asserts the cycle immediately after the third
    // byte is received. out_bytes = {byte1, byte2, byte3} and is valid when done.
    // In the BYTE1 / DONE states the current input is examined for the next
    // message's byte1 (in[3]=1). Synchronous active-high reset.
    localparam BYTE1=2'd0, BYTE2=2'd1, BYTE3=2'd2, DONE=2'd3;

    reg [1:0] state, next;
    reg [7:0] b1, b2, b3;

    always @(*) begin
        case (state)
            BYTE1: next = in[3] ? BYTE2 : BYTE1;
            BYTE2: next = BYTE3;
            BYTE3: next = DONE;
            DONE:  next = in[3] ? BYTE2 : BYTE1;   // examine next byte1 now
            default: next = BYTE1;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state <= BYTE1;
            b1 <= 0; b2 <= 0; b3 <= 0;
        end else begin
            state <= next;
            // capture each byte as it is consumed
            if (state == BYTE1 && in[3]) b1 <= in;
            if (state == DONE  && in[3]) b1 <= in;   // start of next message
            if (state == BYTE2)          b2 <= in;
            if (state == BYTE3)          b3 <= in;
        end
    end

    assign out_bytes = {b1, b2, b3};
    assign done      = (state == DONE);

endmodule
