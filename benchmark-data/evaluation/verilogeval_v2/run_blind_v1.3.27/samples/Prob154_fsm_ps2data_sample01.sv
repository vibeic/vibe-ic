module TopModule(
    input  clk,
    input  reset,
    input  [7:0] in,
    output [23:0] out_bytes,
    output done
);
    localparam S0=2'd0, S1=2'd1, S2=2'd2;

    reg [1:0] state;
    reg       done_r;
    reg [7:0] byte1, byte2, byte3;

    always @(posedge clk) begin
        if (reset) begin
            state  <= S0;
            done_r <= 1'b0;
        end else begin
            case (state)
                S0: begin
                    done_r <= 1'b0;
                    if (in[3]) begin
                        byte1 <= in;
                        state <= S1;
                    end else begin
                        state <= S0;
                    end
                end
                S1: begin
                    done_r <= 1'b0;
                    byte2 <= in;
                    state <= S2;
                end
                S2: begin
                    byte3  <= in;
                    done_r <= 1'b1;
                    state  <= S0;
                end
                default: state <= S0;
            endcase
        end
    end

    assign out_bytes = {byte1, byte2, byte3};
    assign done = done_r;

endmodule
