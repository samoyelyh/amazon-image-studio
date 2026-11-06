/** Revision numbers are server bookkeeping, not a model's semantic decision. */
export function bindPlanSnapshot(name,args,context){
  if(!['generate','revise_visual','revise_modules','revise_and_generate'].includes(name))return args;
  const plan=context?.amazon_plans?.find(p=>p.id===args.plan_id);
  return plan&&Number.isInteger(plan.revision)?{...args,expected_revision:plan.revision}:args;
}
