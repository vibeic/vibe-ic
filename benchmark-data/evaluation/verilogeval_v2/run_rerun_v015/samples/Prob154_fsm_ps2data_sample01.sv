module TopModule(
    input         clk,
    input         reset,
    input  [7:0]  in,
    output [23:0] out_bytes,
    output        done
);
    localparam BYTE1 = 2'd0; // searching for in[3]==1 (first byte)
    localparam BYTE2 = 2'd1;
    localparam BYTE3 = 2'd2;
    localparam DONE  = 2'd3;

    reg [1:0]  state, next;
    reg [23:0] data_r;

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
        if (reset) begin
            state <= BYTE1;
        end else begin
            state <= next;
        end
        // shift incoming bytes into the 24-bit register
        data_r <= {data_r[15:0], in};
    end

    assign done      = (state == DONE);
    assign out_bytes = data_r;
endmodule
