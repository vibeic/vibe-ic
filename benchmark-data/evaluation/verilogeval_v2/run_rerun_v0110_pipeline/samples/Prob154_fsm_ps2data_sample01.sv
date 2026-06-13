module TopModule (
    input             clk,
    input             reset,
    input      [7:0]  in,
    output     [23:0] out_bytes,
    output reg        done
);
    // Discard bytes until one with in[3]=1; that is byte 1 of a 3-byte
    // message. After the 3rd byte is received, assert done in the very next
    // cycle (out_bytes valid that cycle). Then immediately resume searching:
    // the byte present during the done cycle may itself be byte 1 of the next
    // message (waveform shows back-to-back packets with no idle cycle).
    localparam BYTE1 = 2'd0;  // searching for a byte with in[3]=1
    localparam BYTE2 = 2'd1;  // collecting second byte
    localparam BYTE3 = 2'd2;  // collecting third byte

    reg [1:0] state, next;
    reg [7:0] b1, b2, b3;

    always @(*) begin
        case (state)
            BYTE1:   next = in[3] ? BYTE2 : BYTE1;  // start of message on in[3]=1
            BYTE2:   next = BYTE3;
            BYTE3:   next = BYTE1;  // 3rd byte captured; next cycle re-eval byte1
            default: next = BYTE1;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state <= BYTE1;
            done  <= 1'b0;
        end else begin
            state <= next;
            // done pulses the cycle immediately after byte 3 was received.
            done  <= (state == BYTE3);
            // Latch each byte as it is captured.
            if (state == BYTE1 && in[3]) b1 <= in;  // byte 1
            if (state == BYTE2)          b2 <= in;  // byte 2
            if (state == BYTE3)          b3 <= in;  // byte 3
        end
    end

    assign out_bytes = {b1, b2, b3};
endmodule
