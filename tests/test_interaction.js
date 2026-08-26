import assert from 'node:assert/strict';
import { createPointerStateMachine } from '../beatscope/web/pointer.js';

let clicks = 0;
let drags = 0;
const machine = createPointerStateMachine({ onClick: () => { clicks += 1; }, onDrag: () => { drags += 1; } });
machine.pointerdown({ x: 10, y: 10, step: 4 });
machine.pointermove({ x: 12, y: 12, step: 5 });
assert.equal(machine.pointerup({ x: 12, y: 12, step: 5 }), false);
assert.equal(clicks, 1);
assert.equal(drags, 0);

machine.pointerdown({ x: 10, y: 10, step: 4 });
machine.pointermove({ x: 20, y: 10, step: 8 });
assert.equal(machine.pointerup({ x: 30, y: 10, step: 10 }), true);
assert.equal(clicks, 1);
assert.ok(drags > 0);
console.log('Pointer interaction tests passed.');
