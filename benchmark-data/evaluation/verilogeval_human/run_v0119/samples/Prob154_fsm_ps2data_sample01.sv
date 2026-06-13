module TopModule (
  input clk,
  input [7:0] in,
  input reset,
  output [23:0] out_bytes,
  output done
);
    localparam BYTE1 = 2'd0,  // searching for in[3]=1
               BYTE2 = 2'd1,
               BYTE3 = 2'd2,
               DONE  = 2'd3;

    reg [1:0] state, next;
    reg [23:0] shft;
    reg capture;

    always @(*) begin
        case (state)
            BYTE1: begin
                capture = in[3];
                next    = in[3] ? BYTE2 : BYTE1;
            end
            BYTE2: begin capture = 1'b1; next = BYTE3; end
            BYTE3: begin capture = 1'b1; next = DONE;  end
            DONE:  begin
                capture = in[3];
                next    = in[3] ? BYTE2 : BYTE1;
            end
            default: begin capture = 1'b0; next = BYTE1; end
        endcase
    end

    always @(posedge clk) begin
        if (reset) state <= BYTE1;
        else       state <= next;
        if (capture) shft <= {shft[15:0], in};
    end

    assign out_bytes = shft;
    assign done = (state == DONE);
endmodule
