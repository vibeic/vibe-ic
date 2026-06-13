module TopModule (
    input         clk,
    input         reset,
    input  [7:0]  in,
    output [23:0] out_bytes,
    output        done
);
    // Discard bytes until in[3]==1 (= byte1). After byte3 is received, signal done
    // in the cycle IMMEDIATELY AFTER (the DONE cycle). done + out_bytes are valid
    // combinationally in that same DONE cycle (no extra register stage).
    localparam BYTE1 = 2'd0; // hunting for start byte (in[3]==1)
    localparam BYTE2 = 2'd1;
    localparam BYTE3 = 2'd2;
    localparam DONE  = 2'd3; // one cycle after byte3; also acts as BYTE1

    reg [1:0] state, next;
    reg [7:0] b1, b2, b3;

    wire start = (state == BYTE1 || state == DONE) && in[3];

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
        if (reset) state <= BYTE1;
        else       state <= next;
        // capture each byte at the cycle it is sampled
        if (start)          b1 <= in;
        if (state == BYTE2) b2 <= in;
        if (state == BYTE3) b3 <= in;
    end

    // valid in the DONE cycle: b1/b2/b3 hold this message; combinational read uses
    // the pre-edge values so a same-cycle next-message byte1 doesn't corrupt them.
    assign out_bytes = {b1, b2, b3};
    assign done      = (state == DONE);
endmodule
