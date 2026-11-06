"""Requeue one proved-success receipt on its original MySQL Job. No API replay."""
import asyncio,json,sqlite3,sys
from sqlalchemy import select,func
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.db.session import get_engine
from app.core.config import get_settings
from app.agents.dsh_settings import state
from app.models.tasks import Job,JobAttempt
from app.models.content import GeneratedOutput
from app.models.quota import QuotaReservation,QuotaAccount,QuotaTransaction
from app.services.task_service import dispatch_jobs

async def main(id):
    root=state();receipt=root/'worker/receipts'/f'{id}.json'
    with sqlite3.connect(root/'worker/budget.sqlite') as c:
        assert c.execute('SELECT state FROM calls WHERE id=?',(id,)).fetchone()==('succeeded',)
        assert not c.execute("SELECT id FROM calls WHERE state='started'").fetchone()
        count=c.execute('SELECT count(*) FROM calls').fetchone()[0]
    assert receipt.is_file() and json.loads(receipt.read_text()).get('outputs')
    async with async_sessionmaker(get_engine(),expire_on_commit=False)() as db:
        j=await db.get(Job,id,with_for_update=True)
        assert j and j.status=='failed' and (j.input_json.get('metadata') or {}).get('dsh_native')
        assert not await db.scalar(select(GeneratedOutput.id).where(GeneratedOutput.job_id==id))
        assert not await db.scalar(select(Job.id).where(Job.status.in_(['running','dispatching'])))
        reservation=await db.get(QuotaReservation,j.quota_reservation_id)
        assert reservation.status in {'released','expired','reserved'} and not reservation.actual_quantity
        before={'id':id,'status':j.status,'attempts':j.attempts,'reservation_status':reservation.status,'call_count':count}
        (root/('receipt-recovery-'+id+'.json')).write_text(json.dumps(before))
        j.status='queued';j.max_attempts=j.attempts+1;j.dispatched_at=None;j.celery_task_id=None;j.error_code=None;j.error_message=None;j.finished_at=None
        await db.commit();await dispatch_jobs(db,[j])
    print(json.dumps({**before,'recovery':'same Job; original Worker; durable successful receipt','new_generation_requests':0}))
if __name__=='__main__':asyncio.run(main(sys.argv[1]))
