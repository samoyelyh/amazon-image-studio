"""Durable per-call ceilings, independent of user quotas and controller restarts."""
import base64
import gzip
import io
import os
from contextvars import ContextVar
import json
from pathlib import Path
import sqlite3
from time import time
from uuid import uuid4

from app.providers.base import ProviderError, ProviderOutput, ProviderResult

current_job = ContextVar('dsh_experiment_job', default=None)
mcp_call = ContextVar('dsh_experiment_mcp', default=None)

def unpack_native_transcript(payload):
    """Job keeps its 128 KiB limit; owned Session data has a bounded encoding."""
    payload=dict(payload)
    packed=payload.pop('native_transcript_gzip',None)
    if packed is None:return payload
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(base64.b64decode(packed,validate=True))) as stream:
            raw=stream.read(524289)
        if len(raw)>524288:raise ValueError('context limit')
        value=json.loads(raw)
        if set(value)!={'agent_messages','agent_tools'} or not all(isinstance(v,list) for v in value.values()):raise ValueError('transcript contract')
    except (ValueError,TypeError,OSError):raise ProviderError('dsh.transcript_invalid','Invalid or oversized native Session transcript',retryable=False) from None
    return {**payload,**value}


class Ledger:
    def __init__(self, root, limit=50, window=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'budget.sqlite'
        self.limit = limit
        self.window = window if window is not None else os.environ.get('DSH_BUDGET_WINDOW','')
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY, kind TEXT, model TEXT, state TEXT, started REAL, finished REAL, details TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS call_windows(id TEXT PRIMARY KEY, window TEXT NOT NULL)')

    def connection(self):
        return sqlite3.connect(self.path, timeout=30)

    def reserve(self, id, kind, model):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT state,details FROM calls WHERE id=?', (id,)).fetchone()
            if old:
                if old[0] == 'succeeded':
                    return json.loads(old[1])
                known=json.loads(old[1])
                if (kind=='mcp' and old[0]=='not_sent' and known.get('actual_requests')==0
                    and not db.execute('SELECT 1 FROM calls WHERE id=?',(id+':unsent-preflight',)).fetchone()):
                    db.execute('UPDATE calls SET id=? WHERE id=?',(id+':unsent-preflight',id))
                    db.execute('UPDATE call_windows SET id=? WHERE id=?',(id+':unsent-preflight',id))
                else:raise ProviderError('agent.remote_unknown', 'Previous API request may have been charged; automatic resend refused', retryable=False)
            if self.limit is not None:
                count = (db.execute("SELECT count(*) FROM calls c JOIN call_windows w ON w.id=c.id WHERE c.kind=? AND c.state!='not_sent' AND w.window=?",(kind,self.window)).fetchone()[0]
                    if self.window else db.execute("SELECT count(*) FROM calls WHERE kind=? AND state!='not_sent'",(kind,)).fetchone()[0])
                if count >= self.limit:
                    raise ProviderError('experiment.budget_exhausted', 'Experiment call ceiling reached', retryable=False)
            db.execute('INSERT INTO calls VALUES(?,?,?,?,?,?,?)', (id, kind, model, 'started', time(), None, '{}'))
            db.execute('INSERT INTO call_windows VALUES(?,?)',(id,self.window))
        return None

    def finish(self, id, state, details):
        with self.connection() as db:
            db.execute('UPDATE calls SET state=?,finished=?,details=? WHERE id=?', (state, time(), json.dumps(details, ensure_ascii=False), id))

    def summary(self):
        with self.connection() as db:
            db.row_factory = sqlite3.Row
            return {'limit_per_kind': self.limit, 'ceiling_enabled':self.limit is not None, 'window':self.window, 'calls': [dict(r) for r in db.execute('SELECT c.*,w.window FROM calls c LEFT JOIN call_windows w ON w.id=c.id ORDER BY started')],
                    'cost_note': 'API cost is unknown unless returned by the provider; quota credits are not currency.'}


def install_guards(root,limit=50,native_only=False):
    """Durable request guards; limit=None removes only the experiment ceiling."""
    from app.workers.tasks import jobs
    from app.agents.capabilities.mcp_gateway import MCPGateway
    from app.agents import runtime
    ledger = Ledger(root,limit)
    original_execute = jobs._execute_job
    original_adapter = jobs.get_provider_adapter
    original_mcp = MCPGateway.call
    original_connection=MCPGateway.connection
    def connection(self,server):
        result=original_connection(self,server)
        proxy=os.environ.get('DSH_MCP_PROXY_URL')
        if proxy:
            from urllib.parse import urlparse
            parsed=urlparse(proxy)
            approved={'127.0.0.1','localhost',*os.environ.get('DSH_APPROVED_PROXY_HOSTS','').split(',')}
            if parsed.scheme!='http' or parsed.hostname not in approved or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'','/'}:
                raise ValueError('Experiment MCP proxy must be an explicit local HTTP proxy')
            import httpx
            result['httpx_client_factory']=lambda **kwargs:httpx.AsyncClient(**kwargs,trust_env=False,follow_redirects=False,proxy=proxy)
        return result
    MCPGateway.connection=connection
    from mcp import ClientSession
    original_call_tool=ClientSession.call_tool
    async def call_tool(self,name,arguments=None,*args,**kwargs):
        marker=mcp_call.get()
        if marker is not None:marker['actual_requests']+=1
        return await original_call_tool(self,name,arguments,*args,**kwargs)
    ClientSession.call_tool=call_tool
    original_commit = runtime._execute_committed

    async def execute_committed(db,settings,redis,run,plan,permissions,authorized):
        if any(a.get('tool') in {'generate_aplus','generate_chat_images','generate_chat_tryon'} for a in plan.get('actions',[])):
            from sqlalchemy import select
            from app.models.hermes_agent import HermesMessage
            gate=await db.scalar(select(HermesMessage).where(HermesMessage.conversation_id==run.conversation_id,HermesMessage.role=='dsh_fact_gate').order_by(HermesMessage.created_at.desc()).limit(1))
            if gate is not None and not gate.metadata_json.get('confirmed'):
                from app.core.errors import AppError
                raise AppError('experiment.product_facts_required','请确认我方商品事实；竞品调研不能代替商品事实。',409)
        return await original_commit(db,settings,redis,run,plan,permissions,authorized)

    async def execute(job_id, *args, **kwargs):
        token = current_job.set(job_id)
        try:
            return await original_execute(job_id, *args, **kwargs)
        finally:
            current_job.reset(token)

    class GuardedProvider:
        def __init__(self, adapter):
            self.adapter = adapter

        async def execute(self, **kwargs):
            meta=kwargs['payload'].get('metadata') or {}
            if native_only and not (meta.get('dsh_native') or meta.get('workflow')=='dsh_native_session'):
                return await self.adapter.execute(**kwargs)
            id = current_job.get()
            if not id:
                raise ProviderError('experiment.unscoped_call', 'Only an existing Job may invoke a Provider')
            kwargs['payload']=unpack_native_transcript(kwargs['payload'])
            kind = 'text' if kwargs['capability'] == 'text_generation' else 'image'
            receipt_path = ledger.root / 'receipts' / (id + '.json')
            replay = ledger.reserve(id, kind, kwargs['upstream_model'])
            if replay is not None:
                if not receipt_path.is_file():
                    raise ProviderError('agent.remote_unknown', 'Paid result receipt missing; no resend')
                value = json.loads(receipt_path.read_text(encoding='utf-8'))
                return ProviderResult([ProviderOutput(base64.b64decode(o['content']), o['mime_type'], o['filename']) for o in value['outputs']], value['provider_request_id'], value['metadata'])
            try:
                result = await self.adapter.execute(**kwargs)
                receipt_path.parent.mkdir(parents=True, exist_ok=True)
                value = {'outputs': [{'content': base64.b64encode(o.content).decode(), 'mime_type': o.mime_type, 'filename': o.filename} for o in result.outputs],
                         'provider_request_id': result.provider_request_id, 'metadata': result.metadata}
                tmp = receipt_path.with_suffix('.tmp')
                tmp.write_text(json.dumps(value), encoding='utf-8'); tmp.replace(receipt_path)
                meta = result.metadata or {}
                ledger.finish(id, 'succeeded', {'provider_request_id': result.provider_request_id, 'usage': meta.get('usage'), 'transport':meta.get('transport'), 'api_cost': meta.get('cost'), 'outputs': len(result.outputs)})
                return result
            except Exception as error:
                ledger.finish(id, 'failed_or_unknown', {'code': getattr(error, 'code', type(error).__name__), 'http_status': getattr(error, 'http_status', None), 'api_cost': None})
                raise

    async def mcp(self, cap, arguments, **kwargs):
        import hashlib
        key = hashlib.sha256(json.dumps([self.registry.ctx.organization_id, self.registry.ctx.user_id, cap.id, cap.input_schema, arguments], sort_keys=True).encode()).hexdigest()
        id = 'mcp:' + key
        replay = ledger.reserve(id, 'mcp', cap.id)
        if replay is not None:
            return replay['result']
        marker={'actual_requests':0}
        token=mcp_call.set(marker)
        try:
            result = await original_mcp(self, cap, arguments, **kwargs)
            ledger.finish(id, 'succeeded', {'result': result, 'api_cost': None,**marker})
            return result
        except Exception as error:
            ledger.finish(id, 'failed_or_unknown' if marker['actual_requests'] else 'not_sent', {'code': getattr(error, 'code', type(error).__name__),**marker,**getattr(error,'mcp_diagnostics',{})})
            error.requests_sent=marker['actual_requests']
            raise
        finally:
            mcp_call.reset(token)

    jobs._execute_job = execute
    jobs.get_provider_adapter = lambda provider_type, settings: GuardedProvider(original_adapter(provider_type, settings))
    MCPGateway.call = mcp
    runtime._execute_committed=execute_committed
    return ledger
