module TopModule (
    input         clk,
    input         reset,
    input  [7:0]  in,
    output [23:0] out_bytes,
    output        done
);
    localparam BYTE1 = 2'd0;   // searching for first byte (in[3]==1)
    localparam BYTE2 = 2'd1;
    localparam BYTE3 = 2'd2;
    localparam DONE  = 2'd3;   // one cycle after third byte

    reg [1:0]  state, next;
    reg [23:0] shifter;        // accumulates the 3 bytes
    reg [23:0] hold;           // latched output message

    always @(*) begin
        case (state)
            BYTE1: next = in[3] ? BYTE2 : BYTE1;
            BYTE2: next = BYTE3;
            BYTE3: next = DONE;
            DONE:  next = in[3] ? BYTE2 : BYTE1;   // start next msg immediately
            default: next = BYTE1;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state <= BYTE1;
        end else begin
            state <= next;
            case (state)
                BYTE1: if (in[3]) shifter <= {in, 16'b0};       // byte 1 -> [23:16]
                BYTE2: shifter <= {shifter[23:16], in, 8'b0};   // byte 2 -> [15:8]
                BYTE3: begin
                    hold <= {shifter[23:8], in};                 // byte 3 -> [7:0]
                end
                DONE:  if (in[3]) shifter <= {in, 16'b0};       // pipeline next msg
                default: ;
            endcase
        end
    end

    assign out_bytes = hold;
    assign done      = (state == DONE);
endmodule
