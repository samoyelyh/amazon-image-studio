/** Explicit defaults; never silently fall back to a more expensive model. */
export const DEFAULT_MODEL='kimi-for-coding';
export const ALLOWED_MODELS=new Set([DEFAULT_MODEL,'gpt-6.1-terra','gpt-6.1-sol']);
export function modelForRole(role){
  const env=role==='main'?'DSH_MAIN_MODEL':['vision','quality'].includes(role)?'DSH_VISION_MODEL':'DSH_EXECUTOR_MODEL';
  const model=process.env[env]||DEFAULT_MODEL;
  if(!ALLOWED_MODELS.has(model))throw Error('Model is not approved for the DSH experiment');
  return model;
}
export function modelStatus(){return {main:modelForRole('main'),executor:modelForRole('executor'),vision:modelForRole('vision'),reasoning_effort:'low'};}
