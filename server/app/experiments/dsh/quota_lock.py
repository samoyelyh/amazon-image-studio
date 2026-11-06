"""SQLite experiment equivalent of MySQL's quota-account row write lock.

The lock spans the account read and its transaction, never Provider I/O (the
existing Worker commits immediately before entering that boundary).
"""
import asyncio
from pathlib import Path
import os
import time
from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlalchemy.util.concurrency import await_only

roots={}
installed=False

def acquire(path):
    f=open(path,'a+b');f.seek(0)
    deadline=time.monotonic()+30
    while True:
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            return f
        except OSError:
            if time.monotonic()>deadline:f.close();raise TimeoutError('Experiment quota transaction lock timed out')
            time.sleep(.01)

def release(f):
    f.seek(0)
    if os.name=='nt':
        import msvcrt
        msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
    else:
        import fcntl
        fcntl.flock(f,fcntl.LOCK_UN)
    f.close()

def install(root):
    global installed
    root=Path(root).resolve();roots[str(root/'platform.sqlite').lower()]=root/'quota-account.lock'
    if installed:return
    installed=True
    @event.listens_for(Session,'do_orm_execute')
    def lock_account(state):
        if not state.is_select or 'quota_accounts' not in str(state.statement) or state.session.info.get('dsh_quota_lock'):return
        bind=state.session.get_bind()
        if bind.dialect.name!='sqlite' or not bind.url.database or bind.url.database==':memory:':return
        lock=roots.get(str(Path(bind.url.database).resolve()).lower())
        if lock:state.session.info['dsh_quota_lock']=await_only(asyncio.to_thread(acquire,lock))
    @event.listens_for(Session,'after_transaction_end')
    def unlock_account(session,transaction):
        if transaction.parent is None:
            f=session.info.pop('dsh_quota_lock',None)
            if f:release(f)
