"""Real independent MySQL concurrency, ownership and additive rollback rehearsal."""
import asyncio,importlib.util,json,os
from pathlib import Path
from sqlalchemy import select,text,inspect
from sqlalchemy.ext.asyncio import async_sessionmaker
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.db.session import get_engine
from app.db.base import Base
import app.models
from app.models.identity import Organization,User
from app.models.hermes_agent import HermesConversation
from app.models.agent_control import AgentRun
from app.models.quota import QuotaAccount
from app.agents import runtime,dsh_platform
from app.core.errors import AppError

async def main():
    engine=get_engine()
    assert engine.url.database=='dsh_validation' and engine.url.host=='dsh-validation-mysql'
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.drop_all)
        await c.run_sync(Base.metadata.create_all)
    factory=async_sessionmaker(engine,expire_on_commit=False)
    async with factory() as db:
        org=Organization(name='DSH MySQL validation',slug='dsh-mysql-validation');db.add(org)
        users=[User(account='dsh-mysql-'+str(i),display_name='Isolated test',password_hash='disabled') for i in range(2)];db.add_all(users);await db.flush()
        conv=HermesConversation(organization_id=org.id,user_id=users[0].id,controller_type='dsh',mode='chat',title='Durable native conversation');db.add(conv);await db.flush()
        account=QuotaAccount(organization_id=org.id,balance=1000,reserved_balance=0);db.add(account);await db.commit()
        cid,uid,oid=conv.id,users[0].id,org.id;account_id=account.id
        try:await runtime.conversation(db,oid,users[1].id,cid);raise AssertionError('Cross-user allowed')
        except AppError as e:assert e.status_code==404
    async def reserve():
        async with factory() as db:
            a=await db.scalar(select(QuotaAccount).where(QuotaAccount.id==account_id).with_for_update())
            a.reserved_balance+=1;await db.commit()
    await asyncio.gather(*[reserve() for _ in range(20)])
    async with factory() as db:
        a=await db.get(QuotaAccount,account_id);assert a.reserved_balance==20
        await dsh_platform.set_controller(db,'langgraph',uid);assert await dsh_platform.controller(db)=='langgraph'
        await dsh_platform.set_controller(db,'dsh',uid);assert await dsh_platform.controller(db)=='dsh'
        assert (await runtime.conversation(db,oid,uid,cid)).title=='Durable native conversation'
    migration_path=Path('/app/alembic/versions/0064_dsh_controller.py')
    spec=importlib.util.spec_from_file_location('dsh_migration',migration_path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    async with engine.begin() as c:
        def rehearse(sync):
            m.op=Operations(MigrationContext.configure(sync));m.downgrade()
            assert sync.execute(text('SELECT COUNT(*) FROM hermes_conversations')).scalar()==1
            m.upgrade();assert inspect(sync).has_table('agent_controller_settings')
        await c.run_sync(rehearse)
    async with factory() as db:
        await dsh_platform.set_controller(db,'langgraph',uid)
        await dsh_platform.set_controller(db,'dsh',uid)
        assert await dsh_platform.controller(db)=='dsh'
    print(json.dumps({'independent_mysql':True,'concurrent_reservations':20,'lost_updates':0,'foreign_user_denied':True,'controller_roundtrip':True,'conversation_survives_restart_connection':True,'additive_migration_up_down_up':True,'paid_calls':0}))
    await engine.dispose()

if __name__=='__main__':asyncio.run(main())

