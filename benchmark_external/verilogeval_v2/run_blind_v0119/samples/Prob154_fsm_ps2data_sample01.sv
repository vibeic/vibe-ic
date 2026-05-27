module TopModule (
    input         clk,
    input         reset,
    input  [7:0]  in,
    output [23:0] out_bytes,
    output        done
);
    localparam B1   = 2'd0,  // searching for byte1 (in[3]=1)
               B2   = 2'd1,  // collecting byte2
               B3   = 2'd2,  // collecting byte3
               DONE = 2'd3;  // done asserted; also re-searches for next byte1

    reg [1:0] state, next;
    reg [7:0] b1, b2, b3;

    // next-state: B1 and DONE both search for in[3]=1 to begin a packet
    always @(*) begin
        case (state)
            B1:   next = in[3] ? B2 : B1;
            B2:   next = B3;
            B3:   next = DONE;
            DONE: next = in[3] ? B2 : B1;
            default: next = B1;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state <= B1;
        end else begin
            state <= next;
            // capture bytes as they arrive
            case (state)
                B1:   if (in[3]) b1 <= in;          // byte1
                B2:            b2 <= in;            // byte2
                B3:            b3 <= in;            // byte3
                DONE: if (in[3]) b1 <= in;          // start of next packet
                default: ;                          // hold
            endcase
        end
    end

    assign out_bytes = {b1, b2, b3};
    assign done      = (state == DONE);
endmodule
