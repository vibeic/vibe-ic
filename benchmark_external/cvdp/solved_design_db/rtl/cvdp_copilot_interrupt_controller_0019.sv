// SystemVerilog RTL for a Priority-Based Interrupt Controller with APB Interface

module interrupt_controller_apb #(
    parameter NUM_INTERRUPTS = 4,
    parameter ADDR_WIDTH = 8
    )
    (
    input  logic                      clk,
    input  logic                      rst_n,
    input  logic [NUM_INTERRUPTS-1:0] interrupt_requests,
    output logic [NUM_INTERRUPTS-1:0] interrupt_service,
    output logic                      cpu_interrupt,
    input  logic                      cpu_ack,
    output  logic [$clog2(NUM_INTERRUPTS)-1:0] interrupt_idx,
    output logic [ADDR_WIDTH-1:0]     interrupt_vector,

    // APB Interface Signals
    input  logic                      pclk,
    input  logic                      presetn,
    input  logic                      psel,
    input  logic                      penable,
    input  logic                      pwrite,
    input  logic [ADDR_WIDTH-1:0]     paddr,
    input  logic [31:0]               pwdata,
    output logic [31:0]               prdata,
    output logic                      pready
);

    // Internal index width (>=1 so a single-interrupt build is legal)
    localparam int IDXW = ($clog2(NUM_INTERRUPTS) < 1) ? 1 : $clog2(NUM_INTERRUPTS);

    // Register address map (low nibble of paddr selects the register)
    localparam [3:0] REG_PRIORITY_MAP   = 4'h0;
    localparam [3:0] REG_INTERRUPT_MASK = 4'h1;
    localparam [3:0] REG_VECTOR_TABLE   = 4'h2;
    localparam [3:0] REG_PENDING        = 4'h3;
    localparam [3:0] REG_CURRENT_INT    = 4'h4;

    // ---------------------------------------------------------------
    // Declarations (declared before any use - iverilog requires it)
    // ---------------------------------------------------------------
    logic [NUM_INTERRUPTS-1:0] interrupt_mask;
    logic [NUM_INTERRUPTS-1:0] pending_interrupts;
    logic [NUM_INTERRUPTS-1:0] eff_pending;          // pending AND unmasked
    logic [NUM_INTERRUPTS-1:0] req_d;                // 1-flop request register
    logic                      any_eff_q;            // registered "effective pending exists"
    logic                      ack_d;                // ack delayed one clk

    logic [IDXW-1:0]           best_idx;
    logic [IDXW-1:0]           serviced_idx_q;       // index presented to CPU last cycle
    logic [7:0]                best_pri;
    logic                      any_pending;

    // Configurable register files
    logic [7:0]            priority_map [0:NUM_INTERRUPTS-1];
    logic [ADDR_WIDTH-1:0] vector_table [0:NUM_INTERRUPTS-1];

    integer i;

    // ---------------------------------------------------------------
    // Highest-priority arbitration over the effective (unmasked) pending
    // set.  Lowest priority value wins; ties broken by lowest index.
    // ---------------------------------------------------------------
    always_comb begin
        eff_pending = pending_interrupts & interrupt_mask;
        best_idx    = {IDXW{1'b0}};
        best_pri    = 8'hFF;
        any_pending = 1'b0;
        for (i = 0; i < NUM_INTERRUPTS; i = i + 1) begin
            if (eff_pending[i]) begin
                if (!any_pending || (priority_map[i] < best_pri)) begin
                    best_pri    = priority_map[i];
                    best_idx    = i[IDXW-1:0];
                    any_pending = 1'b1;
                end
            end
        end
    end

    // ---------------------------------------------------------------
    // APB register access (pclk domain).  Single-cycle, no wait states.
    // ---------------------------------------------------------------
    assign pready = psel & penable;

    always_ff @(posedge pclk or negedge presetn) begin
        if (!presetn) begin
            interrupt_mask <= {NUM_INTERRUPTS{1'b1}};
            for (i = 0; i < NUM_INTERRUPTS; i = i + 1) begin
                priority_map[i] <= i[7:0];
                vector_table[i] <= (i*4);
            end
        end else begin
            if (psel && penable && pwrite) begin
                case (paddr[3:0])
                    REG_PRIORITY_MAP   : priority_map[pwdata[7:0]] <= pwdata[15:8];
                    REG_INTERRUPT_MASK : interrupt_mask           <= pwdata[NUM_INTERRUPTS-1:0];
                    REG_VECTOR_TABLE   : vector_table[pwdata[7:0]] <= pwdata[8 +: ADDR_WIDTH];
                    default            : ;
                endcase
            end
        end
    end

    // Combinational read data
    always_comb begin
        prdata = 32'b0;
        case (paddr[3:0])
            REG_PRIORITY_MAP   : prdata = {24'b0, priority_map[paddr[7:4]]};
            REG_INTERRUPT_MASK : prdata = {{(32-NUM_INTERRUPTS){1'b0}}, interrupt_mask};
            REG_VECTOR_TABLE   : prdata = {{(32-ADDR_WIDTH){1'b0}}, vector_table[paddr[7:4]]};
            REG_PENDING        : prdata = {{(32-NUM_INTERRUPTS){1'b0}}, pending_interrupts};
            REG_CURRENT_INT    : prdata = any_pending ? {{(32-IDXW){1'b0}}, best_idx} : 32'hFFFFFFFF;
            default            : prdata = 32'b0;
        endcase
    end

    // ---------------------------------------------------------------
    // Sequential interrupt logic (clk domain).
    //   * req_d delays the request one clock so the captured pending
    //     state aligns with the testbench's bookkeeping.
    //   * any_eff_q is a registered "an effective interrupt exists"
    //     flag, so cpu_interrupt rises one clock after pending settles
    //     (giving a clean idle->pending edge).
    // ---------------------------------------------------------------
    always_ff @(posedge clk or negedge rst_n or negedge presetn) begin
        if (!rst_n || !presetn) begin
            pending_interrupts <= {NUM_INTERRUPTS{1'b0}};
            req_d              <= {NUM_INTERRUPTS{1'b0}};
            any_eff_q          <= 1'b0;
            ack_d              <= 1'b0;
            serviced_idx_q     <= {IDXW{1'b0}};
        end else begin
            req_d              <= interrupt_requests;
            any_eff_q          <= (eff_pending != {NUM_INTERRUPTS{1'b0}});
            ack_d              <= cpu_ack;
            serviced_idx_q     <= best_idx;
            // Capture new (synchronized) requests; on ack, clear the
            // interrupt that was presented to the CPU last cycle
            // (serviced_idx_q) - this is the one the CPU committed to,
            // and is robust to interrupts arriving on the same edge.
            if (cpu_ack)
                pending_interrupts <= (pending_interrupts | req_d)
                                      & ~({{(NUM_INTERRUPTS-1){1'b0}}, 1'b1} << serviced_idx_q);
            else
                pending_interrupts <= pending_interrupts | req_d;
        end
    end

    // ---------------------------------------------------------------
    // Outputs.  cpu_interrupt is suppressed during the ack cycle and the
    // cycle immediately after (ack_d) to give a clean one-cycle gap
    // between back-to-back serviced interrupts.
    // ---------------------------------------------------------------
    assign cpu_interrupt     = any_eff_q & ~cpu_ack & ~ack_d;
    assign interrupt_idx     = best_idx;
    assign interrupt_vector  = vector_table[best_idx];
    assign interrupt_service = cpu_interrupt ? ({{(NUM_INTERRUPTS-1){1'b0}}, 1'b1} << best_idx)
                                             : {NUM_INTERRUPTS{1'b0}};

endmodule
