/** Native Harness kernel with no shell, filesystem, SQL, or network tools. */
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
import {mkdirSync,appendFileSync} from 'node:fs';
const require=createRequire(new URL('./harness/package.json',import.meta.url));
const pkg=async name=>import(pathToFileURL(require.resolve('@deepseek-ai/'+name)).href);
const {Context}=await pkg('cordis');
const {LlmAdapter,createUserMessage}=await pkg('dsh-llm');
export async function createNativeRuntime(root, bridge) {
  mkdirSync(root,{recursive:true});
  const ctx=new Context();
  for (const [name,config] of [
    ['cordis-plugin-timer',{}],['dsh-llm',{}],['dsh-session',{}],
    ['dsh-session-projection',{}],['dsh-system-prompt',{includeHarnessIdentity:false,includeRuntimeContext:false,personaPrefix:''}],
    ['dsh-tools',{}],['dsh-agent',{}],
    ['dsh-session-persistence-jsonl',{root:resolve(root,'sessions'),compression:'none'}],
    ['dsh-agent-loop',{agents:[],maxParallelToolCalls:4}],
  ]) {const mod=await pkg(name);ctx.plugin(mod.default||mod,config);}
  // Plugin startup is asynchronous; reject startup rather than silently use a fake driver.
  for(let n=0;n<200 && (!ctx.get('agents')||!ctx.get('agentLoop'));n++)await new Promise(r=>setTimeout(r,20));
  const trace=(type,data)=>appendFileSync(resolve(root,'native-events.jsonl'),JSON.stringify({at:new Date().toISOString(),type,...data})+'\n');
  const responses=new Map();
  class BusinessModel extends LlmAdapter {
    async resolveModel(provider,model){return {provider,id:model,name:model,inputModalities:['text','image'],context:{contextWindow:model==='kimi-for-coding'?1048576:128000}};}
    async *stream(options) {
      trace('model.request',{session:options.sessionId,model:options.model,tools:options.tools?.map(t=>t.name)});
      const started=performance.now();
      const response=await bridge('model',options);
      responses.set(options.sessionId,response);
      let i=0;
      if(response.reasoning_content){yield {type:'block-start',index:i,blockType:'reasoning'};yield {type:'reasoning-delta',index:i,text:response.reasoning_content};yield {type:'block-end',index:i++,block:{type:'reasoning',text:response.reasoning_content}};}
      if(response.text){yield {type:'block-start',index:i,blockType:'text'};yield {type:'text-delta',index:i,text:response.text};yield {type:'block-end',index:i++,block:{type:'text',text:response.text}};}
      for(const call of response.tool_calls||[]){
        yield {type:'block-start',index:i,blockType:'tool-call'};
        yield {type:'tool-call-delta',index:i,id:call.id,name:call.function.name,argumentsDelta:call.function.arguments};
        yield {type:'block-end',index:i++,block:{type:'tool-call',id:call.id,name:call.function.name,arguments:call.function.arguments}};
      }
      if(response.usage)yield {type:'usage',usage:{inputTokens:response.usage.prompt_tokens||0,outputTokens:response.usage.completion_tokens||0,totalTokens:response.usage.total_tokens}};
      trace('model.response',{session:options.sessionId,model:options.model,seconds:(performance.now()-started)/1000,...response});
      yield {type:'finish',reason:{kind:response.tool_calls?.length?'tool-calls':'stop'}};
    }
  }
  ctx.llm.registerAdapter(['platform'],new BusinessModel());
  ctx.on('session/event',(session,event)=>trace('session.event',{session:session.id,event}));
  const active=new Map();
  async function ensure(id,model,prompt,tools){
    if(active.has(id))return active.get(id);
    const setup=(scope,agent)=>{
      scope.systemPrompt.section({name:'business',order:0,text:prompt,interpolate:false,complete:true});
      // No global tools are mounted. This also denies any future global plugin;
      // scoped business registrations remain visible only to their own Session.
      scope.tools.restrict({allow:[]});
      for(const t of tools)scope.tools.register({...t,output:{schema:{type:'object',additionalProperties:true},render:(_,v)=>[{type:'text',text:JSON.stringify(v)}]}});
    };
    let handle;
    const maxTokens=id.startsWith('main-')?1200:id.startsWith('vision-')?2500:id.startsWith('quality-')?3500:12000;
    try {handle=await ctx.agents.resume({resumeSessionId:id,agentOptions:{provider:'platform',model,maxTokens},setup});}
    catch(error){if(!String(error).includes('not found')&&!String(error).includes('not-found'))throw error;
      handle=await ctx.agents.create({sessionId:id,agentOptions:{provider:'platform',model,maxTokens},setup});}
    active.set(id,handle.agent);return handle.agent;
  }
  return {ctx,trace,ensure,result:id=>responses.get(id),async run(agent,id,text){
    responses.delete(agent.id);
    const before=agent.session.events?.length||0;
    agent.followup({...createUserMessage({content:[{type:'text',text}],source:{kind:'user'}}),id});
    await agent.whenIdle();await ctx.parallel('session/flush',agent.session);
    return {session:agent.id,before};
  }};
}
