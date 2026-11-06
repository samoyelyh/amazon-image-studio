"""Local release helper; refuses to update services while any Job is active."""
import argparse,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
STATE=ROOT/'experiments/dsh/.state/deployment'
def main():
 p=argparse.ArgumentParser();p.add_argument('tag');p.add_argument('--sidecar');p.add_argument('--frontend');a=p.parse_args()
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
  config['environment'].update(DSH_BUDGET_WINDOW='creative-director-20261106',DSH_CALL_LIMIT='40')
 if a.sidecar:value['services']['dsh-sidecar']['image']=a.sidecar;names.append('dsh-sidecar')
 if a.frontend:value['services']['frontend']['image']=a.frontend;names.append('frontend')
 release.write_text(json.dumps(value),encoding='utf-8')
 cmd=json.loads((STATE/'compose-command.json').read_text())
 subprocess.run(['docker',*cmd,'-f',str(release),'up','-d','--no-deps',*names],check=True)
 print(json.dumps({'updated':names,'window':'creative-director-20261106','limit_per_kind':40,'prior_receipts':'preserved'}))
if __name__=='__main__':main()
