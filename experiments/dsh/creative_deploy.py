"""Local release helper; refuses to update services while any Job is active."""
import argparse,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
STATE=ROOT/'experiments/dsh/.state/deployment'
def main():
 p=argparse.ArgumentParser();p.add_argument('tag');p.add_argument('--sidecar');p.add_argument('--frontend');p.add_argument('--call-limit',type=int,default=0,help='0 disables the experiment ceiling; positive values opt into acceptance limits.');a=p.parse_args()
 if a.call_limit<0:p.error('--call-limit must be zero or positive')
 subprocess.run(['docker','cp',str(ROOT/'experiments/dsh/deployment_probe.py'),'amazon-image-studio-backend-1:/tmp/dshprobe.py'],check=True)
 probe=json.loads(subprocess.check_output(['docker','exec','-e','PYTHONPATH=/app','amazon-image-studio-backend-1','python','/tmp/dshprobe.py']))
 if any(j['status']=='running' for j in probe['active_jobs']):raise SystemExit('Running Jobs: update postponed, no signals sent.')
 if probe['active_jobs']:
  for state in ['active','reserved']:
   tasks=json.loads(subprocess.check_output(['docker','exec','amazon-image-studio-worker-1','celery','-A','app.workers.celery_app:celery_app','inspect',state,'--json']))
   if not tasks or any(tasks.values()):raise SystemExit('Celery work has not drained; update postponed.')
 release=STATE/'release.json';value=json.loads(release.read_text());backup=STATE/'before-creative-release.json'
 if not backup.exists():backup.write_text(release.read_text(),encoding='utf-8')
 names=['backend','worker','maintenance-worker','queue-retention-worker','celery-beat','flower']
 for name in names:
  config=value['services'][name];config['image']='amazon-image-studio-backend:'+a.tag
  config['environment']['DSH_CALL_LIMIT']=str(a.call_limit)
  for env_file in config.get('env_file',[]):
   path=Path(env_file)
   if path.is_file():
    lines=[line for line in path.read_text(encoding='utf-8').splitlines() if not line.startswith('DSH_CALL_LIMIT=')]
    path.write_text('\n'.join([*lines,'DSH_CALL_LIMIT='+str(a.call_limit)])+'\n',encoding='utf-8')
 if a.sidecar:value['services']['dsh-sidecar']['image']=a.sidecar;names.append('dsh-sidecar')
 if a.frontend:value['services']['frontend']['image']=a.frontend;names.append('frontend')
 release.write_text(json.dumps(value),encoding='utf-8')
 cmd=json.loads((STATE/'compose-command.json').read_text())
 subprocess.run(['docker',*cmd,'-f',str(release),'up','-d','--no-deps',*names],check=True)
 print(json.dumps({'updated':names,'limit_per_kind':a.call_limit or None,'prior_receipts':'preserved'}))
if __name__=='__main__':main()
