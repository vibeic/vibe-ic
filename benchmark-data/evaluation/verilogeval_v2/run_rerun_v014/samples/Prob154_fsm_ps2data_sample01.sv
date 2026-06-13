module TopModule (
    input             clk,
    input             reset,
    input      [7:0]  in,
    output reg [23:0] out_bytes,
    output reg        done
);

    localparam BYTE1 = 2'd0;  // searching for first byte (in[3]==1)
    localparam BYTE2 = 2'd1;  // collecting second byte
    localparam BYTE3 = 2'd2;  // collecting third byte (assert done after)

    reg [1:0] state, next;
    reg [7:0] b1, b2;

    always @(*) begin
        case (state)
            BYTE1: next = in[3] ? BYTE2 : BYTE1;
            BYTE2: next = BYTE3;
            BYTE3: next = in[3] ? BYTE2 : BYTE1;  // after 3rd byte, restart search
            default: next = BYTE1;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= BYTE1;
        else
            state <= next;
    end

    // capture first two bytes
    always @(posedge clk) begin
        if (state == BYTE1) begin
            if (in[3]) b1 <= in;
        end else if (state == BYTE2) begin
            b2 <= in;
        end
    end

    // when collecting the third byte, latch the full message and assert done
    always @(posedge clk) begin
        if (reset) begin
            done      <= 1'b0;
            out_bytes <= 24'b0;
        end else if (state == BYTE3) begin
            done      <= 1'b1;
            out_bytes <= {b1, b2, in};
        end else begin
            done      <= 1'b0;
        end
    end

endmodule
