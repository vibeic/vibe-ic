module alu(
    input  wire [31:0] a,
    input  wire [31:0] b,
    input  wire [5:0]  aluc,
    output wire [31:0] r,
    output wire        zero,
    output wire        carry,
    output wire        negative,
    output wire        overflow,
    output wire        flag
);

parameter ADD  = 6'b100000;
parameter ADDU = 6'b100001;
parameter SUB  = 6'b100010;
parameter SUBU = 6'b100011;
parameter AND  = 6'b100100;
parameter OR   = 6'b100101;
parameter XOR  = 6'b100110;
parameter NOR  = 6'b100111;
parameter SLT  = 6'b101010;
parameter SLTU = 6'b101011;
parameter SLL  = 6'b000000;
parameter SRL  = 6'b000010;
parameter SRA  = 6'b000011;
parameter SLLV = 6'b000100;
parameter SRLV = 6'b000110;
parameter SRAV = 6'b000111;
parameter LUI  = 6'b001111;

wire signed [31:0] sa = a;
wire signed [31:0] sb = b;

reg [32:0] res;

always @(*) begin
    case (aluc)
        ADD:  res = {a[31], a} + {b[31], b};
        ADDU: res = {1'b0, a} + {1'b0, b};
        SUB:  res = {a[31], a} - {b[31], b};
        SUBU: res = {1'b0, a} - {1'b0, b};
        AND:  res = {1'b0, a & b};
        OR:   res = {1'b0, a | b};
        XOR:  res = {1'b0, a ^ b};
        NOR:  res = {1'b0, ~(a | b)};
        SLT:  res = (sa < sb) ? 33'd1 : 33'd0;
        SLTU: res = (a < b) ? 33'd1 : 33'd0;
        SLL:  res = {1'b0, b << a};
        SRL:  res = {1'b0, b >> a};
        SRA:  res = {1'b0, $signed(b) >>> a};
        SLLV: res = {1'b0, b << a[4:0]};
        SRLV: res = {1'b0, b >> a[4:0]};
        SRAV: res = {1'b0, $signed(b) >>> a[4:0]};
        LUI:  res = {1'b0, a[15:0], 16'b0};
        default: res = 33'bz;
    endcase
end

assign r        = res[31:0];
assign zero     = (r == 32'b0);
assign carry    = res[32];
assign negative = r[31];
assign overflow = (aluc == ADD || aluc == ADDU) ? (a[31] == b[31] && r[31] != a[31]) :
                  (aluc == SUB || aluc == SUBU) ? (a[31] != b[31] && r[31] != a[31]) :
                  1'b0;
assign flag     = (aluc == SLT || aluc == SLTU) ? res[0] : 1'bz;

endmodule
