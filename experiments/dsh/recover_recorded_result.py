"""Finish one known successful paid receipt through the original Worker, no resend."""
import asyncio,json,sqlite3,sys
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'server'))
from app.experiments.dsh.environment import STATE,configure
configure()

async def main(id):
    ledger=sqlite3.connect(STATE/'worker/budget.sqlite')
    assert ledger.execute("SELECT state FROM calls WHERE id=?",(id,)).fetchone()==('succeeded',)
    assert not ledger.execute("SELECT 1 FROM calls WHERE state='started'").fetchone(),'Active upstream I/O exists'
    assert (STATE/'worker/receipts'/f'{id}.json').is_file()
    db=sqlite3.connect(STATE/'platform.sqlite');db.row_factory=sqlite3.Row
    active=db.execute("SELECT id FROM jobs WHERE status IN ('running','dispatching')").fetchall()
    assert all(row['id']==id for row in active),'Other platform work is active'
    backup=STATE/'backups'/('before-receipt-recovery-'+datetime.now().strftime('%Y%m%d%H%M%S')+'.sqlite');backup.parent.mkdir(exist_ok=True)
    target=sqlite3.connect(backup);db.backup(target);target.close()
    corrections=[]
    with db:
        for account in db.execute('SELECT id,balance,reserved_balance FROM quota_accounts').fetchall():
            totals=db.execute('SELECT coalesce(sum(balance_delta),0),coalesce(sum(reserved_delta),0) FROM quota_transactions WHERE account_id=?',(account['id'],)).fetchone()
            assert totals[0]==account['balance'] and 0<=totals[1]<=totals[0]
            if account['reserved_balance']!=totals[1]:
                corrections.append({'account':account['id'],'before':account['reserved_balance'],'after':totals[1]})
                db.execute('UPDATE quota_accounts SET reserved_balance=?,version=version+1 WHERE id=?',(totals[1],account['id']))
        db.execute("UPDATE jobs SET status='dispatching',max_attempts=attempts+1,dispatched_at=?,heartbeat_at=?,error_code=NULL,error_message=NULL WHERE id=? AND status='running'",(datetime.now(timezone.utc).isoformat(),datetime.now(timezone.utc).isoformat(),id))
    db.close()
    from app.experiments.dsh import worker
    from app.workers.tasks import jobs
    result=await jobs._execute_job(id)
    report={'job':id,'backup':str(backup),'corrections':corrections,'result':result,'new_provider_requests':0,'basis':'existing successful Worker receipt'}
    (STATE/'recorded-result-recovery.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':asyncio.run(main(sys.argv[1]))
