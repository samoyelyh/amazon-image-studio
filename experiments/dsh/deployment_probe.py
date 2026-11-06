"""Read-only production preflight; outputs counts/hashes, never environment values."""
import asyncio, hashlib, json
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.db.session import get_engine

async def main():
    async with async_sessionmaker(get_engine())() as db:
        result={}
        for table in ['hermes_conversations','agent_runs','jobs','generated_outputs','assets']:
            result[table]=await db.scalar(text('SELECT COUNT(*) FROM '+table))
        result['active_jobs']=[dict(r) for r in (await db.execute(text("SELECT id,status,capability,queue_name FROM jobs WHERE status IN ('pending','queued','dispatching','running','retry_wait')"))).mappings()]
        result['users']=[dict(r) for r in (await db.execute(text('SELECT id,account FROM users LIMIT 10'))).mappings()]
        result['organizations']=[dict(r) for r in (await db.execute(text('SELECT id,slug FROM organizations LIMIT 10'))).mappings()]
        result['mcp_audits']=[dict(r) for r in (await db.execute(text("SELECT id,status,tool_name FROM hermes_tool_audits WHERE status IN ('unknown','running') LIMIT 20"))).mappings()]
        print(json.dumps(result,ensure_ascii=False,default=str))

if __name__=='__main__':asyncio.run(main())
