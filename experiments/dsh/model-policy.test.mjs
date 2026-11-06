import {test} from 'node:test';
import assert from 'node:assert/strict';
import {modelForRole,modelStatus} from './model-policy.mjs';
test('K2.8 is the default for all text/vision roles with no expensive fallback',()=>{
  const names=['DSH_MAIN_MODEL','DSH_EXECUTOR_MODEL','DSH_VISION_MODEL'];const old=names.map(n=>process.env[n]);
  try{
    names.forEach(n=>delete process.env[n]);
    assert.deepEqual(modelStatus(),{main:'kimi-for-coding',executor:'kimi-for-coding',vision:'kimi-for-coding',reasoning_effort:'low'});
    process.env.DSH_MAIN_MODEL='k3.1-pro-highspeed';assert.throws(()=>modelForRole('main'),/not approved/);
  }finally{names.forEach((n,i)=>old[i]===undefined?delete process.env[n]:process.env[n]=old[i]);}
});
