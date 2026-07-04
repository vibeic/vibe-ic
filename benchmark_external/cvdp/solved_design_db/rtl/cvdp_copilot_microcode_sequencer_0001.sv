// Microcode sequencer top level.
// Integrates a LIFO stack, program counter, microcode arithmetic unit,
// instruction decoder and result register to sequence a microcoded system.
module microcode_sequencer (
    input  wire        clk,
    input  wire        c_n_in,     // carry-in for the ripple carry adder
    input  wire        c_inc_in,   // carry-in for the PC incrementer
    input  wire        r_en,       // ACTIVE LOW auxiliary register enable
    input  wire        cc,         // ACTIVE LOW condition code
    input  wire        ien,        // ACTIVE LOW instruction enable
    input  wire [3:0]  d_in,       // data input bus
    input  wire [4:0]  instr_in,   // 5-bit opcode
    input  wire        oen,        // ACTIVE LOW output enable
    output wire [3:0]  d_out,      // address output bus
    output wire        c_n_out,    // carry out from the ripple carry adder
    output wire        c_inc_out,  // carry out from the PC incrementer
    output wire        full,       // LIFO full flag (ACTIVE HIGH)
    output wire        empty       // LIFO empty flag (ACTIVE HIGH)
);

    // Instruction decoder control signals
    wire        cen, rst, oe_dec, inc, rsel, rce, pc_mux_sel;
    wire [1:0]  a_mux_sel, b_mux_sel;
    wire        push, pop, src_sel, stack_we, stack_re, out_ce;

    // Datapath nets
    wire [3:0]  pc_out;
    wire        pc_c_out;
    wire [3:0]  stack_data_out;
    wire [3:0]  arith_d_out;
    wire        arith_cout;
    wire [3:0]  rr_out;

    instruction_decoder u_dec (
        .instr_in   (instr_in),
        .cc_in      (cc),
        .instr_en   (ien),
        .cen        (cen),
        .rst        (rst),
        .oe_dec     (oe_dec),
        .inc        (inc),
        .rsel       (rsel),
        .rce        (rce),
        .pc_mux_sel (pc_mux_sel),
        .a_mux_sel  (a_mux_sel),
        .b_mux_sel  (b_mux_sel),
        .push       (push),
        .pop        (pop),
        .src_sel    (src_sel),
        .stack_we   (stack_we),
        .stack_re   (stack_re),
        .out_ce     (out_ce)
    );

    program_counter u_pc (
        .clk               (clk),
        .full_adder_data_i (arith_d_out),
        .pc_c_in           (c_inc_in),
        .inc               (inc),
        .pc_mux_sel        (pc_mux_sel),
        .pc_out            (pc_out),
        .pc_c_out          (pc_c_out)
    );

    lifo_stack u_stack (
        .clk            (clk),
        .stack_data1_in (d_in),
        .stack_data2_in (pc_out),
        .stack_reset    (rst),
        .stack_push     (push),
        .stack_pop      (pop),
        .stack_mux_sel  (src_sel),
        .stack_we       (stack_we),
        .stack_re       (stack_re),
        .stack_data_out (stack_data_out),
        .full_o         (full),
        .empty_o        (empty)
    );

    microcode_arithmetic u_arith (
        .clk           (clk),
        .fa_in         (arith_d_out),
        .d_in          (d_in),
        .stack_data_in (stack_data_out),
        .pc_data_in    (pc_out),
        .reg_en        (r_en),
        .oen           (oen),
        .rsel          (rsel),
        .rce           (rce),
        .cen           (cen),
        .a_mux_sel     (a_mux_sel),
        .b_mux_sel     (b_mux_sel),
        .arith_cin     (c_n_in),
        .oe            (oe_dec),
        .arith_cout    (arith_cout),
        .d_out         (arith_d_out)
    );

    result_register u_rr (
        .clk      (clk),
        .data_in  (arith_d_out),
        .out_ce   (out_ce),
        .data_out (rr_out)
    );

    assign d_out     = arith_d_out;
    assign c_n_out   = arith_cout;
    assign c_inc_out = pc_c_out;

endmodule


// ---------------------------------------------------------------------------
// Instruction decoder
// ---------------------------------------------------------------------------
module instruction_decoder (
    input  wire [4:0] instr_in,
    input  wire       cc_in,    // ACTIVE LOW condition code
    input  wire       instr_en, // ACTIVE LOW instruction enable
    output reg        cen,
    output reg        rst,
    output reg        oe_dec,   // ACTIVE HIGH full-adder output enable
    output reg        inc,
    output reg        rsel,
    output reg        rce,
    output reg        pc_mux_sel,
    output reg [1:0]  a_mux_sel,
    output reg [1:0]  b_mux_sel,
    output reg        push,
    output reg        pop,
    output reg        src_sel,
    output reg        stack_we,
    output reg        stack_re,
    output reg        out_ce
);
    always @(*) begin
        // Inactive defaults
        cen        = 1'b0;
        rst        = 1'b0;
        oe_dec     = 1'b0;
        inc        = 1'b0;
        rsel       = 1'b0;
        rce        = 1'b0;
        pc_mux_sel = 1'b0;
        a_mux_sel  = 2'b10;   // 0
        b_mux_sel  = 2'b10;   // 0
        push       = 1'b0;
        pop        = 1'b0;
        src_sel    = 1'b0;
        stack_we   = 1'b0;
        stack_re   = 1'b0;
        out_ce     = 1'b0;

        if (!instr_en) begin
            case (instr_in)
                5'b00000: begin // PRST - force d_out to 0, load PC, reset stack
                    rst        = 1'b1;
                    inc        = 1'b1;
                    pc_mux_sel = 1'b1;   // select full_adder_data (=0) into PC
                    oe_dec     = 1'b1;
                    out_ce     = 1'b1;
                    a_mux_sel  = 2'b10;  // 0
                    b_mux_sel  = 2'b10;  // 0
                end
                5'b00001: begin // Fetch PC
                    oe_dec    = 1'b1;
                    inc       = 1'b1;
                    out_ce    = 1'b1;
                    a_mux_sel = 2'b10;   // 0
                    b_mux_sel = 2'b00;   // pc_data
                end
                5'b00010: begin // Fetch R
                    oe_dec    = 1'b1;
                    inc       = 1'b1;
                    out_ce    = 1'b1;
                    a_mux_sel = 2'b01;   // aux_reg
                    b_mux_sel = 2'b10;   // 0
                end
                5'b00011: begin // Fetch D
                    oe_dec    = 1'b1;
                    inc       = 1'b1;
                    out_ce    = 1'b1;
                    a_mux_sel = 2'b00;   // d_in
                    b_mux_sel = 2'b10;   // 0
                end
                5'b00100: begin // Fetch R + D
                    oe_dec    = 1'b1;
                    inc       = 1'b1;
                    out_ce    = 1'b1;
                    cen       = 1'b1;    // allow ripple-carry c_in to affect the R+D sum
                    a_mux_sel = 2'b00;   // d_in
                    b_mux_sel = 2'b11;   // aux_reg
                end
                5'b01011: begin // Push PC
                    push      = 1'b1;
                    stack_we  = 1'b1;
                    src_sel   = 1'b0;    // select pc_in to write
                    inc       = 1'b1;
                    oe_dec    = 1'b1;
                    a_mux_sel = 2'b10;   // 0
                    b_mux_sel = 2'b00;   // pc_data on d_out
                end
                5'b01110: begin // Pop PC
                    pop       = 1'b1;
                    stack_re  = 1'b1;
                    inc       = 1'b1;
                    oe_dec    = 1'b1;
                    out_ce    = 1'b1;
                    a_mux_sel = 2'b10;   // 0
                    b_mux_sel = 2'b01;   // stack_data on d_out
                end
                default: begin
                    // condition-code gated no-op (cc_in kept ACTIVE LOW typ.)
                    cen = cc_in & 1'b0;
                end
            endcase
        end
    end
endmodule


// ---------------------------------------------------------------------------
// Program counter
// ---------------------------------------------------------------------------
module program_counter (
    input  wire       clk,
    input  wire [3:0] full_adder_data_i,
    input  wire       pc_c_in,
    input  wire       inc,
    input  wire       pc_mux_sel,
    output wire [3:0] pc_out,
    output wire       pc_c_out
);
    wire [3:0] pc_mux_out;
    wire [3:0] pc_inc_out;
    wire [3:0] pc_data_out;

    pc_mux u_pc_mux (
        .full_adder_data (full_adder_data_i),
        .pc_data         (pc_data_out),
        .pc_mux_sel      (pc_mux_sel),
        .pc_mux_out      (pc_mux_out)
    );

    pc_incrementer u_pc_inc (
        .pc_c_in    (pc_c_in),
        .inc        (inc),
        .pc_data_in (pc_mux_out),
        .pc_inc_out (pc_inc_out),
        .pc_c_out   (pc_c_out)
    );

    pc_reg u_pc_reg (
        .clk         (clk),
        .pc_data_in  (pc_inc_out),
        .pc_data_out (pc_data_out)
    );

    assign pc_out = pc_data_out;
endmodule

module pc_mux (
    input  wire [3:0] full_adder_data,
    input  wire [3:0] pc_data,
    input  wire       pc_mux_sel,
    output wire [3:0] pc_mux_out
);
    assign pc_mux_out = pc_mux_sel ? full_adder_data : pc_data;
endmodule

module pc_incrementer (
    input  wire       pc_c_in,
    input  wire       inc,
    input  wire [3:0] pc_data_in,
    output wire [3:0] pc_inc_out,
    output wire       pc_c_out
);
    wire [4:0] sum = inc ? ({1'b0, pc_data_in} + pc_c_in) : {1'b0, pc_data_in};
    assign pc_inc_out = sum[3:0];
    assign pc_c_out   = inc ? sum[4] : 1'b0;
endmodule

module pc_reg (
    input  wire       clk,
    input  wire [3:0] pc_data_in,
    output reg  [3:0] pc_data_out
);
    always @(posedge clk)
        pc_data_out <= pc_data_in;
endmodule


// ---------------------------------------------------------------------------
// LIFO stack
// ---------------------------------------------------------------------------
module lifo_stack (
    input  wire       clk,
    input  wire [3:0] stack_data1_in, // d_in
    input  wire [3:0] stack_data2_in, // pc
    input  wire       stack_reset,
    input  wire       stack_push,
    input  wire       stack_pop,
    input  wire       stack_mux_sel,
    input  wire       stack_we,
    input  wire       stack_re,
    output wire [3:0] stack_data_out,
    output wire       full_o,
    output wire       empty_o
);
    wire [4:0] stack_addr;
    wire [3:0] mux_out;

    stack_data_mux u_mux (
        .data_in       (stack_data1_in),
        .pc_in         (stack_data2_in),
        .stack_mux_sel (stack_mux_sel),
        .stack_mux_out (mux_out)
    );

    stack_pointer u_sp (
        .clk        (clk),
        .rst        (stack_reset),
        .push       (stack_push),
        .pop        (stack_pop),
        .stack_addr (stack_addr),
        .full       (full_o),
        .empty      (empty_o)
    );

    stack_ram u_ram (
        .clk            (clk),
        .stack_addr     (stack_addr),
        .stack_data_in  (mux_out),
        .stack_we       (stack_we),
        .stack_re       (stack_re),
        .stack_data_out (stack_data_out)
    );
endmodule

module stack_pointer (
    input  wire       clk,
    input  wire       rst,
    input  wire       push,
    input  wire       pop,
    output reg  [4:0] stack_addr,
    output wire       full,
    output wire       empty
);
    assign full  = (stack_addr == 5'd16);
    assign empty = (stack_addr == 5'd0);

    initial stack_addr = 5'd0;

    always @(posedge clk) begin
        if (rst)
            stack_addr <= 5'd0;
        else if (push && !full)
            stack_addr <= stack_addr + 5'd1;
        else if (pop && !empty)
            stack_addr <= stack_addr - 5'd1;
    end
endmodule

module stack_ram (
    input  wire       clk,
    input  wire [4:0] stack_addr,
    input  wire [3:0] stack_data_in,
    input  wire       stack_we,
    input  wire       stack_re,
    output reg  [3:0] stack_data_out
);
    reg [3:0] mem [0:16];

    always @(posedge clk) begin
        if (stack_we)
            mem[stack_addr] <= stack_data_in;
        if (stack_re)
            stack_data_out <= mem[stack_addr];
    end
endmodule

module stack_data_mux (
    input  wire [3:0] data_in,
    input  wire [3:0] pc_in,
    input  wire       stack_mux_sel,
    output wire [3:0] stack_mux_out
);
    assign stack_mux_out = stack_mux_sel ? data_in : pc_in;
endmodule


// ---------------------------------------------------------------------------
// Microcode arithmetic
// ---------------------------------------------------------------------------
module microcode_arithmetic (
    input  wire       clk,
    input  wire [3:0] fa_in,         // full-adder feedback
    input  wire [3:0] d_in,
    input  wire [3:0] stack_data_in,
    input  wire [3:0] pc_data_in,
    input  wire       reg_en,        // r_en (ACTIVE LOW)
    input  wire       oen,           // ACTIVE LOW output enable
    input  wire       rsel,
    input  wire       rce,
    input  wire       cen,
    input  wire [1:0] a_mux_sel,
    input  wire [1:0] b_mux_sel,
    input  wire       arith_cin,
    input  wire       oe,            // ACTIVE HIGH output enable
    output wire       arith_cout,
    output wire [3:0] d_out
);
    wire [3:0] reg_mux_out;
    wire [3:0] aux_reg_out;
    wire [3:0] a_mux_out;
    wire [3:0] b_mux_out;
    wire [3:0] sum;
    wire       carry;

    aux_reg_mux u_aux_reg_mux (
        .reg1_in     (fa_in),
        .reg2_in     (d_in),
        .rsel        (rsel),
        .re          (reg_en),
        .reg_mux_out (reg_mux_out)
    );

    aux_reg u_aux_reg (
        .clk     (clk),
        .reg_in  (reg_mux_out),
        .rce     (rce),
        .re      (reg_en),
        .reg_out (aux_reg_out)
    );

    a_mux u_a_mux (
        .register_data (aux_reg_out),
        .data_in       (d_in),
        .a_mux_sel     (a_mux_sel),
        .a_mux_out     (a_mux_out)
    );

    b_mux u_b_mux (
        .register_data (aux_reg_out),
        .stack_data    (stack_data_in),
        .pc_data       (pc_data_in),
        .b_mux_sel     (b_mux_sel),
        .b_mux_out     (b_mux_out)
    );

    full_adder u_full_adder (
        .a_in  (a_mux_out),
        .b_in  (b_mux_out),
        .c_in  (arith_cin),
        .cen   (cen),
        .c_out (sum),
        .carry (carry)
    );

    assign d_out      = (oe & ~oen) ? sum : 4'b0000;
    assign arith_cout = carry;
endmodule

module aux_reg_mux (
    input  wire [3:0] reg1_in,
    input  wire [3:0] reg2_in,
    input  wire       rsel,
    input  wire       re,        // ACTIVE LOW
    output wire [3:0] reg_mux_out
);
    wire sel = rsel & ~re;
    assign reg_mux_out = sel ? reg1_in : reg2_in;
endmodule

module aux_reg (
    input  wire       clk,
    input  wire [3:0] reg_in,
    input  wire       rce,
    input  wire       re,        // ACTIVE LOW
    output reg  [3:0] reg_out
);
    wire en = rce | ~re;
    initial reg_out = 4'b0000;
    always @(posedge clk)
        if (en)
            reg_out <= reg_in;
endmodule

module a_mux (
    input  wire [3:0] register_data,
    input  wire [3:0] data_in,
    input  wire [1:0] a_mux_sel,
    output reg  [3:0] a_mux_out
);
    always @(*) begin
        case (a_mux_sel)
            2'b00:   a_mux_out = data_in;
            2'b01:   a_mux_out = register_data;
            2'b10:   a_mux_out = 4'b0000;
            default: a_mux_out = 4'b0000;
        endcase
    end
endmodule

module b_mux (
    input  wire [3:0] register_data,
    input  wire [3:0] stack_data,
    input  wire [3:0] pc_data,
    input  wire [1:0] b_mux_sel,
    output reg  [3:0] b_mux_out
);
    always @(*) begin
        case (b_mux_sel)
            2'b00:   b_mux_out = pc_data;
            2'b01:   b_mux_out = stack_data;
            2'b10:   b_mux_out = 4'b0000;
            2'b11:   b_mux_out = register_data;
            default: b_mux_out = 4'b0000;
        endcase
    end
endmodule

module full_adder (
    input  wire [3:0] a_in,
    input  wire [3:0] b_in,
    input  wire       c_in,
    input  wire       cen,
    output wire [3:0] c_out,
    output wire       carry
);
    wire [4:0] s = a_in + b_in + (cen ? c_in : 1'b0);
    assign c_out = s[3:0];
    assign carry = s[4];
endmodule


// ---------------------------------------------------------------------------
// Result register
// ---------------------------------------------------------------------------
module result_register (
    input  wire       clk,
    input  wire [3:0] data_in,
    input  wire       out_ce,
    output reg  [3:0] data_out
);
    initial data_out = 4'b0000;
    always @(posedge clk)
        if (out_ce)
            data_out <= data_in;
endmodule
