module TopModule (
    input         clk,
    input         reset,
    input  [7:0]  in,
    output [23:0] out_bytes,
    output        done
);
    localparam BYTE1 = 2'd0, BYTE2 = 2'd1, BYTE3 = 2'd2, DONE = 2'd3;
    reg [1:0] state, next;
    reg [23:0] shifter;

    always @(*) begin
        case (state)
            BYTE1: next = in[3] ? BYTE2 : BYTE1; // wait for start byte
            BYTE2: next = BYTE3;
            BYTE3: next = DONE;
            DONE : next = in[3] ? BYTE2 : BYTE1; // next message
            default: next = BYTE1;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state <= BYTE1;
        end else begin
            state <= next;
        end
        // shift in the incoming byte (first byte is MSB of out_bytes)
        shifter <= {shifter[15:0], in};
    end

    assign done = (state == DONE);
    assign out_bytes = shifter;
endmodule
