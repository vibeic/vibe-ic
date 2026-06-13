Design a `fixed_priority_arbiter` module in SystemVerilog within a file fixed_priority_arbiter.sv at the location:rtl/fixed_priority_arbiter.v. Refer to the specification provided in docs/specification.md and ensure you understand its content. The specification details the arbitration mechanism, request handling logic, priority override functionality, an example of arbitration behavior, the required module interface, internal architecture, and timing requirements. Generate the complete RTL code that implements the `fixed_priority_arbiter`, which follows a fixed-priority arbitration scheme while allowing an external priority override mechanism.
# Fixed Priority Arbiter Specification Document

## Introduction

The **Fixed Priority Arbiter** is designed to handle **arbitration among multiple requesters** using a **fixed-priority scheme**. It ensures that **only one request** is granted at a time, following a **fixed priority order** (lowest index has the highest priority).  

Additionally, the arbiter **supports external priority overrides**, allowing dynamic control of the granted request. The module operates synchronously with **one-cycle arbitration latency** and provides **valid and grant index outputs** to indicate which request was granted.

---

## Arbitration Overview

The **fixed-priority arbitration** logic follows these steps:

1. **Check Priority Override:**  
   - If `priority_override` is **non-zero**, it takes precedence over the `req` input.
   - The **highest-priority bit** in `priority_override` is granted.

2. **Fixed Priority Selection:**  
   - If `priority_override` is **zero**, the arbiter **scans `req` from bit 0 to 7**.
   - The **first active request** (lowest index) is granted.

3. **Grant Output:**  
   - The grant signal (`grant`) has a **single bit set** corresponding to the granted request.
   - The `grant_index` output provides the **binary index** of the granted request.
   - The `valid` signal is set **high** if a request is granted.

4. **Reset Behavior:**  
   - When `reset` is asserted, the arbiter **clears all outputs** (`grant`, `grant_index`, `valid`).

---

## Module Interface

The module should be defined as follows:

```verilog
module fixed_priority_arbiter(
    input clk,                     
    input reset,                    
    input [7:0] req,                
    input [7:0] priority_override,  

    output reg [7:0] grant,        
    output reg valid,              
    output reg [2:0] grant_index    
);
```

## Port Description
| **Signal**          | **Direction** | **Description**                                                |
|---------------------|---------------|----------------------------------------------------------------|
| `clk`               | **Input**     | System clock (all operations occur on the rising edge).        |
| `reset`             | **Input**     | Active-high synchronous reset (clears all outputs).            |
| `req`               | **Input**     | 8-bit request signal. Each bit represents a requester.         |
| `priority_override` | **Input**     | Allows external modules to force a specific grant.             |
| `grant`             | **Output**    | 8-bit grant signal; only **one bit** is set based on priority. |
| `valid`             | **Output**    | High (`1`) when a grant is issued.                             |
| `grant_index`       | **Output**    | 3-bit index of the granted request.                            |

---

## Internal Architecture

The **Fixed Priority Arbiter** consists of the following components:

### **1. Priority Override Logic**
- Checks if `priority_override` is **non-zero**.
- If so, grants the **highest-priority bit** in `priority_override`.

### **2. Fixed Priority Selection Logic**
- If `priority_override` is **zero**, the arbiter **scans `req` from bit 0 to bit 7**.
- The **lowest active bit** is granted.

### **3. Grant Signal Generation**
- Generates an **8-bit grant signal** with **a single active bit**.
- The corresponding **binary index** is assigned to `grant_index`.

### **4. Output Registering**
- Ensures that **outputs are stable** until the next clock cycle.
- `valid` is set high (`1`) if a request is granted.

---

## Timing and Latency

The **fixed-priority arbitration** is a **single-cycle operation**, meaning that:
| **Operation**           | **Latency (Clock Cycles)** |
|-------------------------|----------------------------|
| **Request Arbitration** | 1 clock cycle              |
| **Priority Override**   | 1 clock cycle              |
| **Reset**               | 1 clock cycle              |

This ensures **fast response times** for **high-speed applications**.

---

