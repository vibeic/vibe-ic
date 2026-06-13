module TopModule (
    input         clk,
    input         reset,
    input  [7:0]  in,
    output [23:0] out_bytes,
    output        done
);
    localparam B1 = 2'd0;  // searching for byte1 (in[3]==1)
    localparam B2 = 2'd1;  // capture byte2
    localparam B3 = 2'd2;  // capture byte3

    reg [1:0]  state, next;
    reg [7:0]  b1, b2, b3;
    reg        done_r;

    always @(*) begin
        case (state)
            B1: next = in[3] ? B2 : B1;
            B2: next = B3;
            B3: next = B1;
            default: next = B1;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state  <= B1;
            done_r <= 1'b0;
            b1 <= 8'd0; b2 <= 8'd0; b3 <= 8'd0;
        end else begin
            state <= next;
            // capture bytes
            case (state)
                B1: if (in[3]) b1 <= in;
                B2: b2 <= in;
                B3: b3 <= in;
                default: ;
            endcase
            // done asserts the cycle right after byte3 captured
            done_r <= (state == B3);
        end
    end

    assign out_bytes = {b1, b2, b3};
    assign done      = done_r;

endmodule
