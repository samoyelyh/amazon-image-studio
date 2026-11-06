import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createNativeRuntime} from './native-runtime.mjs';

test('official Agent Loop executes scoped native tool calls and commits durable Session events',async()=>{
  const root=mkdtempSync(join(tmpdir(),'dsh-native-contract-'));let calls=0;let executed=0;
  const runtime=await createNativeRuntime(root,async()=>{
    calls++;return calls===1?{tool_calls:[{id:'contract-tool-1',function:{name:'business_probe',arguments:'{"value":"owned"}'}}]}:{text:'done'};
  });
  const agent=await runtime.ensure('contract-session','contract-model','Use the scoped business tool.',[{
    name:'business_probe',description:'Contract probe only; no provider request.',
    parameters:{type:'object',properties:{value:{type:'string'}},required:['value'],additionalProperties:false},
    execute:async args=>{assert.equal(args.value,'owned');executed++;return {ok:true};},
  }]);
  await runtime.run(agent,'contract-request','run');
  assert.equal(executed,1);assert.equal(calls,2);
  const records=readFileSync(join(root,'native-events.jsonl'),'utf8').trim().split('\n').map(JSON.parse);
  assert.ok(records.some(r=>r.event?.type==='assistant/message'&&r.event.data.message.content.some(b=>b.type==='tool-call')));
  assert.ok(records.some(r=>r.event?.type==='turn/end'&&r.event.data.reason.kind==='completed'));
  assert.equal(records.filter(r=>r.type==='model.request')[0].tools.join(','),'business_probe');
});
