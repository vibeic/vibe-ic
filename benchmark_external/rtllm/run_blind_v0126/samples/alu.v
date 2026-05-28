module alu (
    input  [31:0] a,
    input  [31:0] b,
    input  [5:0]  aluc,
    output [31:0] r,
    output        zero,
    output        carry,
    output        negative,
    output        overflow,
    output        flag
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

    assign r = res[31:0];

    // flag is result of slt / sltu, high-Z otherwise
    assign flag = (aluc == SLT)  ? ($signed(a) < $signed(b)) :
                  (aluc == SLTU) ? (a < b) :
                  1'bz;

    assign zero     = (res[31:0] == 32'b0) ? 1'b1 : 1'b0;
    assign carry    = res[32];
    assign negative = res[31];
    // overflow for signed add/sub
    assign overflow = ((aluc == ADD) & (a[31] == b[31]) & (res[31] != a[31])) |
                      ((aluc == SUB) & (a[31] != b[31]) & (res[31] != a[31]));

    always @(*) begin
        case (aluc)
            ADD:  res = {sa[31], sa} + {sb[31], sb};
            ADDU: res = a + b;
            SUB:  res = {sa[31], sa} - {sb[31], sb};
            SUBU: res = a - b;
            AND:  res = {1'b0, a & b};
            OR:   res = {1'b0, a | b};
            XOR:  res = {1'b0, a ^ b};
            NOR:  res = {1'b0, ~(a | b)};
            SLT:  res = {33{1'b0}} | (($signed(a) < $signed(b)) ? 33'd1 : 33'd0);
            SLTU: res = {33{1'b0}} | ((a < b) ? 33'd1 : 33'd0);
            SLL:  res = {1'b0, (b << a)};
            SRL:  res = {1'b0, (b >> a)};
            SRA:  res = {1'b0, (sb >>> a)};
            SLLV: res = {1'b0, (b << a[4:0])};
            SRLV: res = {1'b0, (b >> a[4:0])};
            SRAV: res = {1'b0, (sb >>> a[4:0])};
            LUI:  res = {1'b0, a[15:0], 16'b0};
            default: res = {33{1'bz}};
        endcase
    end

endmodule
