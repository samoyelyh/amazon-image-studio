import { createServer } from 'node:http'
import { resolve } from 'node:path'
import { timingSafeEqual } from 'node:crypto'
import { PlatformController } from './controller.ts'
import { createNativeController } from './native-controller.mjs'

const token=process.env.DSH_INTERNAL_TOKEN
if (!token || token.length<32) throw new Error('DSH_INTERNAL_TOKEN of at least 32 characters is required')
const controller=new PlatformController(resolve(process.env.DSH_STATE_DIR || 'experiments/dsh/.state/core','dsh.sqlite'),true)
const native=await createNativeController(resolve(process.env.DSH_STATE_DIR || 'experiments/dsh/.state/core'),controller,token)
const server=createServer(async(req,res)=>{
  const respond=(status:number,value:unknown)=>{res.writeHead(status,{'content-type':'application/json','cache-control':'no-store'});res.end(JSON.stringify(value))}
  const supplied=Buffer.from(String(req.headers['x-dsh-token']||'')),expected=Buffer.from(token)
  if(supplied.length!==expected.length || !timingSafeEqual(supplied,expected)) return respond(403,{error:'forbidden'})
  try {
    if(req.method==='GET' && req.url==='/health') return respond(200,{status:'ok',implementation:'official-dsh-core+native-harness',harness:true,shell_tools:0,upstream:'8c32a9dc5d72c033816c6a8110b37f40cf94fba4'})
    if(req.method!=='POST') return respond(405,{error:'method_not_allowed'})
    let data='';for await(const chunk of req){data+=chunk;if(data.length>128000)throw Object.assign(new Error('Payload too large'),{status:413})}
    const x=JSON.parse(data)
    if(!x.org||!x.user)throw Object.assign(new Error('Authenticated owner required'),{status:400})
    const route=String(req.url)
    if(route==='/native/intake') return respond(200,native.intake(x))
    if(route==='/native/status') return respond(200,native.status(x))
    if(route==='/native/recover') return respond(200,native.recover(x))
    if(route==='/intake') {const result=controller.intake(x);if(result.route==='stopped')native.stop(x,result.ticket);return respond(200,result)}
    if(route==='/tickets') return respond(200,controller.list(x,x.session))
    if(route==='/bind') return respond(200,controller.bind(x,x.ticket,x.conversation))
    if(route==='/report') return respond(200,controller.report(x,x.ticket,x.state,x.summary))
    return respond(404,{error:'not_found'})
  }catch(e:any){respond(e.status||400,{error:e.message})}
})
server.listen(Number(process.env.DSH_PORT||18871),'127.0.0.1',()=>console.log('Official DSH core Sidecar ready on loopback'))
process.on('SIGTERM',()=>server.close(()=>{controller.repo.db.close();process.exit(0)}))
