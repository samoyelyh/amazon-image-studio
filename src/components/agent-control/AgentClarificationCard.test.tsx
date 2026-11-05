import {expect,it,vi} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import type {AgentRun} from '../../lib/agentControlApi'
import {AgentClarificationCard,AgentSuggestionsCard} from './AgentClarificationCard'
import {AgentPlanCard} from './AgentChatCards'
import {MemoryRouter} from 'react-router-dom'
const run:AgentRun={id:'r',conversation_id:'c',status:'needs_input',revision:1,planner_mode:'mock',
  plan:{schema_version:1,summary:'希望使用什么场景？',actions:[{tool:'show_message',arguments:{}}],image_count:0,may_charge:false,cost_note:'',needs_input:['clarification']},
  result:{},error_code:null,state_signature:null,confirmation_token:null,events:[],jobs:[],workspace_url:null}
it('offers a real editable reply and AI suggestion action, without exposing internal need codes',()=>{
  const html=renderToStaticMarkup(<MemoryRouter><AgentPlanCard run={run} status={{enabled:true,writes_enabled:true,model_calls_enabled:true,checkpoint_configured:true,planner_mode:'mock'}} busy={false} onConfirm={vi.fn()} onStop={vi.fn()}/><AgentClarificationCard run={run} busy={false} answered={false} onReply={vi.fn()} onSuggest={vi.fn()}/></MemoryRouter>)
  expect(html).toContain('填写补充说明');expect(html).toContain('补充并继续');expect(html).toContain('让 AI 给我建议');expect(html).not.toContain('clarification')
})
it('keeps submitted clarification visible without claiming image generation succeeded',()=>{
  const html=renderToStaticMarkup(<AgentClarificationCard run={run} busy={false} answered onReply={vi.fn()} onSuggest={vi.fn()}/>)
  expect(html).toContain('已发送补充说明');expect(html).toContain('再次补充');expect(html).not.toContain('生成成功')
})
it('suggestions are editable and do not create a task just by rendering',()=>{
  const adopt=vi.fn()
  const html=renderToStaticMarkup(<AgentSuggestionsCard run={{...run,result:{creative_suggestions:{summary:'创作建议',options:[{title:'白底',instruction:'保持球衣图案，改为白底'}]}}}} busy={false} onAdopt={adopt}/>)
  expect(html).toContain('编辑建议 1');expect(html).toContain('采用此方案并继续');expect(adopt).not.toHaveBeenCalled()
})
