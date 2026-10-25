# Three-phase controller

Parameters:
idle, phase_a, phase_b: Enumeration values representing different states of the controller.

Implementation:
The state transition case statement handles each state. Here is a summary of each state:
idle: Initial state. Transition to phase_a state occurs immediately.
phase_a: Waits for a count of 7 before transitioning to phase_b state. Otherwise, it remains in phase_a state.
phase_b: Waits for a count of 2 before transitioning to idle state. Otherwise, it remains in phase_b state.

Operations:
SUM_UNSIGNED: An arithmetic opcode, not a state definition.
