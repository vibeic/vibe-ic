// instr_reg — instruction register: captures instructions from two sources and
// splits the stored instruction into opcode / register-address / full-data fields.
module instr_reg (
    input  wire        clk,
    input  wire        rst,        // active-low reset
    input  wire [1:0]  fetch,      // 1=register source, 2=RAM/ROM source
    input  wire [7:0]  data,
    output wire [2:0]  ins,        // high 3 bits of instruction (opcode)
    output wire [4:0]  ad1,        // low 5 bits (register address)
    output wire [7:0]  ad2         // full 8-bit data from the second source
);

    reg [7:0] ins_p1; // instruction from source 1
    reg [7:0] ins_p2; // instruction from source 2

    always @(posedge clk) begin
        if (!rst) begin
            ins_p1 <= 8'b0;
            ins_p2 <= 8'b0;
        end else begin
            case (fetch)
                2'b01:   ins_p1 <= data;
                2'b10:   ins_p2 <= data;
                default: begin
                    ins_p1 <= ins_p1;
                    ins_p2 <= ins_p2;
                end
            endcase
        end
    end

    assign ins = ins_p1[7:5];
    assign ad1 = ins_p1[4:0];
    assign ad2 = ins_p2;

endmodule
