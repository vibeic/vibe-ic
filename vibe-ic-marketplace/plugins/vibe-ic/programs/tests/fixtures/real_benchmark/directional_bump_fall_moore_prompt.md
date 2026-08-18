Create a Moore state machine for a creature that walks and falls. Walking left
(walk_left is 1), walking right (walk_right is 1), and falling (aaah is 1) are
the three Moore output behaviours.

If it is bumped on the left, it will walk right. If it is bumped on the right,
it will walk left. If it is bumped on both sides, it will switch directions.
When ground=0, the creature will fall. When ground reappears, it will resume in
the same direction as before the fall. Being bumped while falling does not
affect the walking direction. Being bumped in the same cycle as ground
disappears does not affect the walking direction. Ground reappears while still
falling, and being bumped then does not affect the walking direction.

The state machine changes state on the positive edge of clk. areset is a
positive edge triggered asynchronous reset, resetting the machine to walk left.

module TopModule (
    input clk,
    input areset,
    input bump_left,
    input bump_right,
    input ground,
    output walk_left,
    output walk_right,
    output aaah
);
