"""Authenticated tools/list only; never sends ASIN tools/call or retries research."""
import asyncio,json,os,logging
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.db.session import get_engine
from app.core.config import get_settings
from app.models.identity import User,Organization
from app.security.principal import resolve_principal
from app.agents.capabilities.registry import CapabilityRegistry,digest
from app.agents.capabilities.contracts import ExecutionContext
from app.agents.capabilities.mcp_gateway import MCPGateway,safe_error

async def main():
    logging.disable(logging.CRITICAL)
    # Same mounted credential and controlled gateway as the backend entrypoint.
    os.environ['AGENT_MCP_SS_MCP_SECRET']=Path('/run/secrets/ss_mcp').read_text().strip()
    from app.experiments.dsh.ledger import install_guards
    install_guards('/state/worker',native_only=True)
    async with async_sessionmaker(get_engine())() as db:
        user=await db.scalar(select(User).where(User.account=='dshaccept'))
        org=await db.scalar(select(Organization).where(Organization.slug=='default-organization'))
        p=await resolve_principal(db,user.id,org.id)
        reg=CapabilityRegistry(get_settings(),ExecutionContext(org.id,user.id,'mcp-metadata-probe','metadata-only',p.permissions))
        server=next(s for s in reg.mcp.values() if s.profile=='sellersprite')
        try:
            tools=await MCPGateway(reg).discover(server)
            approved={t.name:t for t in server.tools}
            report={'tools_list_succeeded':True,'discovered_tools':len(tools),'schema_matches':{t['name']:digest(t['input_schema'])==digest(approved[t['name']].input_schema) for t in tools if t['name'] in approved},'tools_call_count':0,'research_executed':False}
        except Exception as e:
            def types(error):
                return [type(error).__name__]+[name for child in getattr(error,'exceptions',[]) for name in types(child)]
            report={'tools_list_succeeded':False,'error_code':safe_error(e),'exception_types':types(e),'tools_call_count':0,'research_executed':False}
        print(json.dumps(report))
if __name__=='__main__':asyncio.run(main())
