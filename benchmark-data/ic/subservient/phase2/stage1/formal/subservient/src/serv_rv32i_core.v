// serv_rv32i_core.v
// GENERATED (authored from L1-L9 spec) — RV32I-faithful compact CPU core.
//
// Spec basis:
//   L2: "SERV core RV32I bit-serial CPU". The L2/L8 docs grant the Plugin full
//   freedom on internal micro-architecture ("單一 flatten module 若 RTL 撰寫策略
//   偏好", "自行決定 SERV 與 servile 是否拆分") so long as the RV32I instruction
//   *semantics* (RISC-V ISA standard) are preserved and the external SRAM-bus
//   contract (L3/L8) is met. This core implements an RV32I-faithful multi-cycle
//   datapath that fetches/loads/stores through a generic synchronous memory bus.
//
// Clean-room implementation: no reference RTL was read.
// Single clock (i_clk), synchronous active-high reset (i_rst) per L2/L3.

module serv_rv32i_core #(
    parameter integer AW       = 10,            // memory byte-address width (memsize=1024 -> 10)
    parameter [31:0]  RESET_PC = 32'h00000000
) (
    input  wire            i_clk,
    input  wire            i_rst,        // synchronous, active-high
    output reg  [AW-1:0]   o_mem_addr,
    output reg  [31:0]     o_mem_wdata,
    input  wire [31:0]     i_mem_rdata,
    input  wire            i_mem_ack,    // word access complete (from servile adapter)
    output reg             o_mem_we,
    output reg             o_mem_re,
    output reg  [3:0]      o_mem_be,
    output reg             o_mem_cyc,
    output reg             o_gpio_we,
    output reg  [7:0]      o_gpio_wdata
);

    // RV32I opcodes (standard encoding)
    localparam [6:0] OP_LUI    = 7'b0110111;
    localparam [6:0] OP_AUIPC  = 7'b0010111;
    localparam [6:0] OP_JAL    = 7'b1101111;
    localparam [6:0] OP_JALR   = 7'b1100111;
    localparam [6:0] OP_BRANCH = 7'b1100011;
    localparam [6:0] OP_LOAD   = 7'b0000011;
    localparam [6:0] OP_STORE  = 7'b0100011;
    localparam [6:0] OP_OPIMM  = 7'b0010011;
    localparam [6:0] OP_OP     = 7'b0110011;
    localparam [6:0] OP_FENCE  = 7'b0001111;  // Zifencei: NOP at memory-model level
    localparam [6:0] OP_SYSTEM = 7'b1110011;

    // FSM states
    localparam [2:0] S_FETCH_ISS = 3'd0;  // issue fetch (addr+re)
    localparam [2:0] S_FETCH_CAP = 3'd1;  // capture instruction
    localparam [2:0] S_DECEX     = 3'd2;  // decode/execute, issue load/store
    localparam [2:0] S_LOAD_CAP  = 3'd3;  // capture load data + writeback
    localparam [2:0] S_STORE_WT  = 3'd4;  // wait for store completion ack

    reg [2:0]  state;
    reg [31:0] pc;
    reg [31:0] next_pc;
    reg [31:0] instr;

    // register file (x0 hardwired to 0)
    reg [31:0] regfile [0:31];

    // decode fields
    wire [6:0]  opcode = instr[6:0];
    wire [4:0]  rd     = instr[11:7];
    wire [2:0]  funct3 = instr[14:12];
    wire [4:0]  rs1    = instr[19:15];
    wire [4:0]  rs2    = instr[24:20];
    wire [6:0]  funct7 = instr[31:25];

    // immediates
    wire [31:0] imm_i = {{20{instr[31]}}, instr[31:20]};
    wire [31:0] imm_s = {{20{instr[31]}}, instr[31:25], instr[11:7]};
    wire [31:0] imm_b = {{19{instr[31]}}, instr[31], instr[7], instr[30:25], instr[11:8], 1'b0};
    wire [31:0] imm_u = {instr[31:12], 12'b0};
    wire [31:0] imm_j = {{11{instr[31]}}, instr[31], instr[19:12], instr[20], instr[30:21], 1'b0};

    // operand reads (x0 == 0)
    wire [31:0] rv1 = (rs1 == 5'd0) ? 32'b0 : regfile[rs1];
    wire [31:0] rv2 = (rs2 == 5'd0) ? 32'b0 : regfile[rs2];

    // ALU operand-b
    reg [31:0] alu_b;
    always @(*) begin
        if (opcode == OP_OP) alu_b = rv2;
        else                 alu_b = imm_i;
    end
    wire [4:0] shamt = alu_b[4:0];

    // arithmetic for OP / OP-IMM
    reg [31:0] arith_res;
    always @(*) begin
        case (funct3)
            3'b000: begin
                if (opcode == OP_OP && funct7[5]) arith_res = rv1 - alu_b;
                else                              arith_res = rv1 + alu_b;
            end
            3'b001:  arith_res = rv1 << shamt;
            3'b010:  arith_res = ($signed(rv1) < $signed(alu_b)) ? 32'd1 : 32'd0;
            3'b011:  arith_res = (rv1 < alu_b) ? 32'd1 : 32'd0;
            3'b100:  arith_res = rv1 ^ alu_b;
            3'b101:  arith_res = funct7[5] ? ($signed(rv1) >>> shamt) : (rv1 >> shamt);
            3'b110:  arith_res = rv1 | alu_b;
            3'b111:  arith_res = rv1 & alu_b;
            default: arith_res = 32'b0;
        endcase
    end

    // branch comparator
    reg branch_taken;
    always @(*) begin
        case (funct3)
            3'b000:  branch_taken = (rv1 == rv2);
            3'b001:  branch_taken = (rv1 != rv2);
            3'b100:  branch_taken = ($signed(rv1) <  $signed(rv2));
            3'b101:  branch_taken = ($signed(rv1) >= $signed(rv2));
            3'b110:  branch_taken = (rv1 <  rv2);
            3'b111:  branch_taken = (rv1 >= rv2);
            default: branch_taken = 1'b0;
        endcase
    end

    // ALU result mux for register writeback
    reg [31:0] alu_out;
    always @(*) begin
        case (opcode)
            OP_LUI:   alu_out = imm_u;
            OP_AUIPC: alu_out = pc + imm_u;
            OP_JAL:   alu_out = pc + 32'd4;
            OP_JALR:  alu_out = pc + 32'd4;
            OP_OPIMM: alu_out = arith_res;
            OP_OP:    alu_out = arith_res;
            default:  alu_out = 32'b0;
        endcase
    end

    // load data alignment (word-aligned external return)
    reg [31:0] load_res;
    always @(*) begin
        case (funct3)
            3'b000:  load_res = {{24{i_mem_rdata[7]}},  i_mem_rdata[7:0]};
            3'b001:  load_res = {{16{i_mem_rdata[15]}}, i_mem_rdata[15:0]};
            3'b010:  load_res = i_mem_rdata;
            3'b100:  load_res = {24'b0, i_mem_rdata[7:0]};
            3'b101:  load_res = {16'b0, i_mem_rdata[15:0]};
            default: load_res = i_mem_rdata;
        endcase
    end

    // effective address
    wire [31:0] mem_eaddr = (opcode == OP_STORE) ? (rv1 + imm_s) : (rv1 + imm_i);

    // GPIO memory-mapped store window: top word of the address space
    localparam [AW-1:0] GPIO_OFF = {AW{1'b1}} & {{(AW-2){1'b1}}, 2'b00};
    wire is_gpio_store = (opcode == OP_STORE) && (mem_eaddr[AW-1:0] == GPIO_OFF);

    // store byte-enable + data shaping
    reg [3:0]  st_be;
    reg [31:0] st_data;
    always @(*) begin
        case (funct3)
            3'b000:  begin st_be = 4'b0001; st_data = {24'b0, rv2[7:0]};  end // SB
            3'b001:  begin st_be = 4'b0011; st_data = {16'b0, rv2[15:0]}; end // SH
            default: begin st_be = 4'b1111; st_data = rv2;                end // SW
        endcase
    end

    integer i;
    always @(posedge i_clk) begin
        if (i_rst) begin
            state        <= S_FETCH_ISS;
            pc           <= RESET_PC;
            next_pc      <= RESET_PC;
            instr        <= 32'b0;
            o_mem_addr   <= {AW{1'b0}};
            o_mem_we     <= 1'b0;
            o_mem_re     <= 1'b0;
            o_mem_wdata  <= 32'b0;
            o_mem_be     <= 4'b0;
            o_mem_cyc    <= 1'b0;
            o_gpio_we    <= 1'b0;
            o_gpio_wdata <= 8'b0;
            for (i = 0; i < 32; i = i + 1)
                regfile[i] <= 32'b0;
        end else begin
            o_gpio_we <= 1'b0;  // single-cycle strobe default
            case (state)
                S_FETCH_ISS: begin
                    o_mem_addr <= pc[AW-1:0];
                    o_mem_re   <= 1'b1;
                    o_mem_we   <= 1'b0;
                    o_mem_be   <= 4'b1111;
                    o_mem_cyc  <= 1'b1;       // one-cycle request; adapter latches it
                    state      <= S_FETCH_CAP;
                end

                S_FETCH_CAP: begin
                    o_mem_re  <= 1'b0;
                    o_mem_cyc <= 1'b0;        // deassert request while adapter works
                    if (i_mem_ack) begin
                        instr <= i_mem_rdata;
                        state <= S_DECEX;
                    end
                end

                S_DECEX: begin
                    o_mem_re  <= 1'b0;
                    o_mem_we  <= 1'b0;
                    o_mem_cyc <= 1'b0;
                    case (opcode)
                        OP_LOAD: begin
                            o_mem_addr <= mem_eaddr[AW-1:0];
                            o_mem_re   <= 1'b1;
                            o_mem_cyc  <= 1'b1;
                            o_mem_be   <= 4'b1111;
                            next_pc    <= pc + 32'd4;
                            state      <= S_LOAD_CAP;
                        end
                        OP_STORE: begin
                            next_pc <= pc + 32'd4;
                            if (is_gpio_store) begin
                                o_gpio_we    <= 1'b1;
                                o_gpio_wdata <= rv2[7:0];
                                pc    <= pc + 32'd4;
                                state <= S_FETCH_ISS;   // GPIO write is single-cycle
                            end else begin
                                o_mem_addr  <= mem_eaddr[AW-1:0];
                                o_mem_wdata <= st_data;
                                o_mem_we    <= 1'b1;
                                o_mem_cyc   <= 1'b1;
                                o_mem_be    <= st_be;
                                state <= S_STORE_WT;    // wait for memory store ack
                            end
                        end
                        OP_BRANCH: begin
                            pc    <= branch_taken ? (pc + imm_b) : (pc + 32'd4);
                            state <= S_FETCH_ISS;
                        end
                        OP_JAL: begin
                            if (rd != 5'd0) regfile[rd] <= pc + 32'd4;
                            pc    <= pc + imm_j;
                            state <= S_FETCH_ISS;
                        end
                        OP_JALR: begin
                            if (rd != 5'd0) regfile[rd] <= pc + 32'd4;
                            pc    <= (rv1 + imm_i) & 32'hFFFF_FFFE;
                            state <= S_FETCH_ISS;
                        end
                        OP_FENCE, OP_SYSTEM: begin
                            pc    <= pc + 32'd4;
                            state <= S_FETCH_ISS;
                        end
                        default: begin // LUI/AUIPC/OPIMM/OP
                            if (rd != 5'd0) regfile[rd] <= alu_out;
                            pc    <= pc + 32'd4;
                            state <= S_FETCH_ISS;
                        end
                    endcase
                end

                S_LOAD_CAP: begin
                    o_mem_re  <= 1'b0;
                    o_mem_cyc <= 1'b0;
                    if (i_mem_ack) begin
                        if (rd != 5'd0) regfile[rd] <= load_res;
                        pc    <= next_pc;
                        state <= S_FETCH_ISS;
                    end
                end

                S_STORE_WT: begin
                    o_mem_we  <= 1'b0;
                    o_mem_cyc <= 1'b0;
                    if (i_mem_ack) begin
                        pc    <= next_pc;
                        state <= S_FETCH_ISS;
                    end
                end

                default: state <= S_FETCH_ISS;
            endcase
        end
    end

endmodule
