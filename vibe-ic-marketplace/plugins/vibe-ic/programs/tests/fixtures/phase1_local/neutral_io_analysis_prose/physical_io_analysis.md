# Physical I/O analysis
This document discusses tools and authoring roles, not pin declarations.
Source SDC input authority takes precedence over a derived PDK/default environment value. Verify the actual emitted deck and native readback/negative controls for physical input slew, ideal-clock slew and external load separately. Do not silently overwrite any selected value with lower-tier defaults.
Append the companion SDC once after the existing clock definitions and I/O windows; it introduces no additional create_clock command. Preserve old proposals and expectations as history, then refresh citations and native pack identity only after ROOT formally adopts this new engineering input revision.
