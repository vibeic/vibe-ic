module TopModule (
    input         clk,
    input         reset,
    input  [7:0]  in,
    output [23:0] out_bytes,
    output        done
);
    localparam BYTE1 = 2'd0;  // wait for in[3]=1 (first byte)
    localparam BYTE2 = 2'd1;
    localparam BYTE3 = 2'd2;
    localparam DONE  = 2'd3;

    reg [1:0]  state, next;
    reg [23:0] shifter;

    always @(*) begin
        case (state)
            BYTE1: next = in[3] ? BYTE2 : BYTE1;
            BYTE2: next = BYTE3;
            BYTE3: next = DONE;
            DONE:  next = in[3] ? BYTE2 : BYTE1;  // immediately look for next msg
            default: next = BYTE1;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state   <= BYTE1;
            shifter <= 24'd0;
        end else begin
            state <= next;
            // shift bytes in (first byte ends up in [23:16])
            if ((state == BYTE1 && in[3]) || state == BYTE2 || state == BYTE3 ||
                (state == DONE && in[3]))
                shifter <= {shifter[15:0], in};
        end
    end

    assign done      = (state == DONE);
    assign out_bytes = shifter;
endmodule
