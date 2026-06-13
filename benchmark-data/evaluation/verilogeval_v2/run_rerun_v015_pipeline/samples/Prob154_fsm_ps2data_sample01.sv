module TopModule (
    input         clk,
    input         reset,
    input  [7:0]  in,
    output [23:0] out_bytes,
    output        done
);
    // Search for byte with in[3]=1 (byte1), then collect 2 more bytes,
    // assert done the cycle AFTER the 3rd byte is received.
    localparam BYTE1 = 2'd0; // searching for first byte (in[3]==1)
    localparam BYTE2 = 2'd1; // collecting second byte
    localparam BYTE3 = 2'd2; // collecting third byte
    localparam DONE  = 2'd3; // done asserted

    reg [1:0] state, next;
    reg [7:0] b1, b2, b3;

    always @(*) begin
        case (state)
            BYTE1: next = in[3] ? BYTE2 : BYTE1;
            BYTE2: next = BYTE3;
            BYTE3: next = DONE;
            DONE:  next = in[3] ? BYTE2 : BYTE1; // immediately reuse current byte
            default: next = BYTE1;
        endcase
    end

    // Capture bytes. b1 captured when a valid first byte arrives;
    // b2 in BYTE2, b3 in BYTE3.
    always @(posedge clk) begin
        if (state == BYTE1 && in[3]) b1 <= in;
        else if (state == DONE && in[3]) b1 <= in;
        if (state == BYTE2) b2 <= in;
        if (state == BYTE3) b3 <= in;
    end

    always @(posedge clk) begin
        if (reset) state <= BYTE1;
        else       state <= next;
    end

    assign done      = (state == DONE);
    assign out_bytes = {b1, b2, b3};
endmodule
