module TopModule (
    input        clk,
    input        x,
    input  [2:0] y,
    output reg   Y0,
    output reg   z
);
    // Combinational next-state (Y0 = bit 0 of next state) and Moore output z.
    always @(*) begin
        Y0 = 1'b0;
        z  = 1'b0;
        case (y)
            3'b000: begin Y0 = x ? 1'b1 : 1'b0; z = 1'b0; end // next 001/000
            3'b001: begin Y0 = x ? 1'b0 : 1'b1; z = 1'b0; end // next 100/001
            3'b010: begin Y0 = x ? 1'b1 : 1'b0; z = 1'b0; end // next 001/010
            3'b011: begin Y0 = x ? 1'b0 : 1'b1; z = 1'b1; end // next 010/001
            3'b100: begin Y0 = x ? 1'b0 : 1'b1; z = 1'b1; end // next 100/011
            default: begin Y0 = 1'b0; z = 1'b0; end
        endcase
    end
endmodule
