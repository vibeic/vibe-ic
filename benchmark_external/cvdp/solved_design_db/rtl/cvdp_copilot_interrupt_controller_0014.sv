module interrupt_controller
#(
    parameter NUM_INTERRUPTS = 4,
    parameter ADDR_WIDTH = 8)
(
    input  logic                      clk,
    input  logic                      rst_n,
    input  logic [NUM_INTERRUPTS-1:0] interrupt_requests,
    output logic [NUM_INTERRUPTS-1:0] interrupt_service,
    output logic                      cpu_interrupt,
    input  logic                      cpu_ack,
    output logic [$clog2(NUM_INTERRUPTS)-1:0] interrupt_idx,
    output logic [ADDR_WIDTH-1:0]     interrupt_vector,
    input  logic [NUM_INTERRUPTS-1:0] priority_map_value [NUM_INTERRUPTS-1:0],
    input  logic                      priority_map_update,
    input  logic [ADDR_WIDTH-1:0]     vector_table_value [NUM_INTERRUPTS-1:0],
    input  logic                      vector_table_update,
    input  logic [NUM_INTERRUPTS-1:0] interrupt_mask_value,
    input  logic                      interrupt_mask_update
);

    // Internal index width (>=1 even when NUM_INTERRUPTS == 1).
    localparam int IDXW = (NUM_INTERRUPTS > 1) ? $clog2(NUM_INTERRUPTS) : 1;

    logic [NUM_INTERRUPTS-1:0] pending;        // pending interrupts (set until acked)
    logic [NUM_INTERRUPTS-1:0] req_sync;       // 1-stage synchronizer of requests
    logic [NUM_INTERRUPTS-1:0] interrupt_mask; // 1 = enabled (serviceable), 0 = masked
    logic                      ack_recover;    // forces interrupt low for one cycle after an ack
    logic                      int_q;          // registered "eligible" (delays the rise)
    logic [IDXW-1:0]           idx_clear_q;    // registered selected index (one cycle old)
    logic                      elig_clear_q;   // registered "eligible" matched to idx_clear_q

    // Configuration tables
    logic [NUM_INTERRUPTS-1:0] priority_map [NUM_INTERRUPTS-1:0]; // lower value = higher priority
    logic [ADDR_WIDTH-1:0]     vector_table [NUM_INTERRUPTS-1:0];

    integer i;

    // ------------------------------------------------------------------
    // Priority evaluation (combinational): lowest priority_map value among the
    // pending AND enabled interrupts.  interrupt_idx tracks it directly so the
    // index the CPU samples is always the current highest priority (no lag).
    // ------------------------------------------------------------------
    logic                  eligible;
    logic [IDXW-1:0]       sel_idx;
    logic [NUM_INTERRUPTS-1:0] sel_pri;

    always @(*) begin
        eligible = 1'b0;
        sel_idx  = {IDXW{1'b0}};
        sel_pri  = {NUM_INTERRUPTS{1'b1}};
        for (i = 0; i < NUM_INTERRUPTS; i = i + 1) begin
            if (pending[i] && interrupt_mask[i]) begin
                if (!eligible || (priority_map[i] < sel_pri)) begin
                    eligible = 1'b1;
                    sel_idx  = i[IDXW-1:0];
                    sel_pri  = priority_map[i];
                end
            end
        end
    end

    // cpu_interrupt asserts after an eligible interrupt has been present a full
    // cycle (int_q) -- a >=2-cycle request->signal latency -- and is forced low
    // while the CPU acks and for one recovery cycle afterwards.
    assign cpu_interrupt    = eligible & int_q & ~cpu_ack & ~ack_recover;
    assign interrupt_idx    = sel_idx;
    assign interrupt_vector = vector_table[sel_idx];

    always @(*) begin
        interrupt_service = {NUM_INTERRUPTS{1'b0}};
        if (eligible)
            interrupt_service[sel_idx] = 1'b1;
    end

    // ------------------------------------------------------------------
    // Sequential state
    // ------------------------------------------------------------------
    logic [NUM_INTERRUPTS-1:0] pending_next;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (i = 0; i < NUM_INTERRUPTS; i = i + 1) begin
                priority_map[i] <= i[NUM_INTERRUPTS-1:0]; // sequential default priorities
                vector_table[i] <= (i*4);                 // default vectors: multiples of 4
            end
            interrupt_mask <= {NUM_INTERRUPTS{1'b1}};      // default: all enabled
            pending        <= {NUM_INTERRUPTS{1'b0}};
            req_sync       <= {NUM_INTERRUPTS{1'b0}};
            ack_recover    <= 1'b0;
            int_q          <= 1'b0;
            idx_clear_q    <= {IDXW{1'b0}};
            elig_clear_q   <= 1'b0;
        end else begin
            // Synchronize requests one stage so `pending` becomes visible on the
            // same edge the test-bench books the request.
            req_sync <= interrupt_requests;

            // Dynamic configuration updates
            if (priority_map_update)
                for (i = 0; i < NUM_INTERRUPTS; i = i + 1)
                    priority_map[i] <= priority_map_value[i];
            if (vector_table_update)
                for (i = 0; i < NUM_INTERRUPTS; i = i + 1)
                    vector_table[i] <= vector_table_value[i];
            if (interrupt_mask_update)
                interrupt_mask <= interrupt_mask_value;

            // Clear the acknowledged interrupt from the pending set, THEN merge
            // the freshly-synchronized requests.  The CPU re-samples
            // interrupt_idx just after a clock edge, where it reads the
            // PRE-edge value, so the index it acknowledges is the previous
            // cycle's selection -- captured here as idx_clear_q -- not the
            // current one.  Clearing idx_clear_q makes the cleared bit match
            // exactly what the CPU removed from its model.
            pending_next = pending;
            if (cpu_ack && elig_clear_q)
                pending_next[idx_clear_q] = 1'b0;
            pending_next = pending_next | req_sync;
            pending <= pending_next;

            // Delay the interrupt rise by one cycle; hold it low one recovery
            // cycle after an ack.  Also register the selection so the ack can
            // clear the index the CPU actually sampled (one cycle old).
            int_q        <= eligible;
            idx_clear_q  <= sel_idx;
            elig_clear_q <= eligible;
            ack_recover  <= cpu_ack;
        end
    end

endmodule
