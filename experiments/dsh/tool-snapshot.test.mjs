import {test} from 'node:test';
import assert from 'node:assert/strict';
import {bindPlanSnapshot} from './tool-snapshot.mjs';
test('binds only the owned read-context snapshot; never guesses or increments a revision',()=>{
 const args={plan_id:'owned',expected_revision:3,module_id:'hero'};
 assert.deepEqual(bindPlanSnapshot('revise_visual',args,{amazon_plans:[{id:'owned',revision:1}]}),{...args,expected_revision:1});
 assert.equal(args.expected_revision,3);
 assert.equal(bindPlanSnapshot('revise_visual',args,{amazon_plans:[{id:'other',revision:7}]}),args);
 assert.equal(bindPlanSnapshot('produce_aplus',args,{amazon_plans:[{id:'owned',revision:1}]}),args);
});
