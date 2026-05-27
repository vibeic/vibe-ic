module TopModule(
    input        clk,
    input        reset,
    input  [7:0] in,
    output [23:0] out_bytes,
    output       done
);
    localparam BYTE1=2'd0, BYTE2=2'd1, BYTE3=2'd2, DONEST=2'd3;
    reg [1:0] state, next;
    reg [7:0] b1, b2, b3;

    always @(*) begin
        case (state)
            BYTE1:  next = in[3] ? BYTE2 : BYTE1;   // wait for header byte
            BYTE2:  next = BYTE3;
            BYTE3:  next = DONEST;
            DONEST: next = in[3] ? BYTE2 : BYTE1;   // next message may start immediately
            default: next = BYTE1;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state <= BYTE1;
        end else begin
            state <= next;
            case (state)
                BYTE1:  if (in[3]) b1 <= in;
                BYTE2:  b2 <= in;
                BYTE3:  b3 <= in;
                DONEST: if (in[3]) b1 <= in;
                default: ;
            endcase
        end
    end

    assign out_bytes = {b1, b2, b3};
    assign done = (state == DONEST);
endmodule
