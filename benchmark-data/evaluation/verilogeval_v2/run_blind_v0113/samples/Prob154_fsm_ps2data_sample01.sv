module TopModule(
    input         clk,
    input         reset,
    input  [7:0]  in,
    output [23:0] out_bytes,
    output        done
);
    localparam B1   = 2'd0;  // searching for byte1 (in[3]==1)
    localparam B2   = 2'd1;  // collecting byte2
    localparam B3   = 2'd2;  // collecting byte3
    localparam DONE = 2'd3;  // message complete, assert done

    reg [1:0]  state;
    reg [7:0]  b1, b2, b3;

    always @(posedge clk) begin
        if (reset) begin
            state <= B1;
        end else begin
            case (state)
                B1: begin
                    if (in[3]) begin
                        b1    <= in;
                        state <= B2;
                    end
                end
                B2: begin
                    b2    <= in;
                    state <= B3;
                end
                B3: begin
                    b3    <= in;
                    state <= DONE;
                end
                DONE: begin
                    // done asserted this cycle; also begin next message search now
                    if (in[3]) begin
                        b1    <= in;
                        state <= B2;
                    end else begin
                        state <= B1;
                    end
                end
                default: state <= B1;
            endcase
        end
    end

    assign out_bytes = {b1, b2, b3};
    assign done      = (state == DONE);
endmodule
