"""Private, reversible local deployment state. Never prints credentials."""
import json,os,secrets,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
STATE=ROOT/'experiments/dsh/.state/deployment'
STATE.mkdir(exist_ok=True,parents=True)
def capture(args):return subprocess.check_output(['docker',*args],text=True,encoding='utf-8')
def inspect(name):return json.loads(capture(['inspect',name]))[0]
def main():
    before=STATE/'before.json'
    if not before.exists():
        names=['backend','frontend','worker','maintenance-worker','queue-retention-worker','celery-beat','flower','mysql']
        before.write_text(json.dumps({n:inspect('amazon-image-studio-'+n+'-1') for n in names}),encoding='utf-8')
    prior=json.loads(before.read_text(encoding='utf-8'))
    runtime=dict(x.split('=',1) for x in prior['backend']['Config']['Env'])
    for name in ['backend','worker','maintenance-worker','queue-retention-worker','celery-beat','flower']:
        env=dict(x.split('=',1) for x in prior[name]['Config']['Env'])
        env.update(DSH_ENABLED='true',DSH_PLATFORM_STATE_DIR='/state',DSH_SIDECAR_URL='http://dsh-sidecar:18871',DSH_APPROVED_PROXY_HOSTS='host.docker.internal',DSH_CALL_LIMIT='0')
        # Formal operation keeps durable guards without an experiment lifetime ceiling.
        (STATE/(name+'.env')).write_text('\n'.join(k+'='+v for k,v in env.items()),encoding='utf-8')
    token_file=STATE/'token'
    if not token_file.exists():token_file.write_text(secrets.token_urlsafe(48),encoding='utf-8')
    token=token_file.read_text()
    for name in ['backend','worker','maintenance-worker','queue-retention-worker','celery-beat','flower']:
        p=STATE/(name+'.env');p.write_text(p.read_text(encoding='utf-8')+'\nDSH_INTERNAL_TOKEN='+token+'\n',encoding='utf-8')
    (STATE/'sidecar.env').write_text('\n'.join(['DSH_INTERNAL_TOKEN='+token,'DSH_MAIN_MODEL=kimi-for-coding','DSH_EXECUTOR_MODEL=kimi-for-coding','DSH_VISION_MODEL=kimi-for-coding','DSH_BUSINESS_URL=http://backend:8000/api/v1/experiment/native/']),encoding='utf-8')
    config={}
    for name in ['backend','worker','maintenance-worker','queue-retention-worker','celery-beat','flower']:
        config[name]={'image':'amazon-image-studio-backend:dsh-20261106','env_file':[str(STATE/(name+'.env'))],
            'environment':dict(x.split('=',1) for x in (STATE/(name+'.env')).read_text(encoding='utf-8').splitlines() if '=' in x),
            'volumes':[str(STATE/'runtime')+':/state'],'stop_grace_period':'960s'}
    config['worker']['command']=['sh','-c','exec '+prior['worker']['Config']['Cmd'][2].replace('$','$$')]
    config['frontend']={'image':'amazon-image-studio-frontend:dsh-20261106'}
    config['dsh-sidecar']={'image':'ais-dsh-native:20261106','env_file':[str(STATE/'sidecar.env')],
        'volumes':[str(STATE/'runtime')+':/state'],'networks':['platform'],'restart':'unless-stopped'}
    # Compose JSON is supported by Docker Compose. Secrets reside in ignored env files.
    (STATE/'release.json').write_text(json.dumps({'services':config}),encoding='utf-8')
    (STATE/'rollback.json').write_text(json.dumps({'services':{n:{'image':prior[n]['Config']['Image'],'environment':{'DSH_ENABLED':'false'}} for n in prior if n!='mysql'}}),encoding='utf-8')
    files=prior['backend']['Config']['Labels']['com.docker.compose.project.config_files'].split(',')
    command=['compose','-p','amazon-image-studio']
    for p in files:command+=['-f',p]
    (STATE/'compose-command.json').write_text(json.dumps(command),encoding='utf-8')
    dump=STATE/'before-mysql.sql'
    if not dump.exists():
        with dump.open('wb') as out:
            subprocess.run(['docker','exec','amazon-image-studio-mysql-1','sh','-c','MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --routines --triggers --set-gtid-purged=OFF "$MYSQL_DATABASE"'],stdout=out,check=True)
    print(json.dumps({'snapshot':True,'mysql_backup_bytes':dump.stat().st_size,'active_task_mutations':0,'default':'dsh','model':'kimi-for-coding','acceptance_call_limit':None}))
if __name__=='__main__':main()
