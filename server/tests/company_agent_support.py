"""Isolated disk storage and Worker provider used by company acceptance probes."""
import json
from pathlib import Path
from app.services.storage_service import StorageService,StorageObjectMetadata


class DiskTestStorage(StorageService):
    def __init__(self,path):self.root=Path(path).resolve();self.root.mkdir(parents=True,exist_ok=True)
    def path(self,key):
        path=(self.root/key).resolve()
        if not path.is_relative_to(self.root):raise ValueError('unsafe test storage key')
        return path
    def upload(self,key,data,*,content_type,metadata=None):
        path=self.path(key);path.parent.mkdir(parents=True,exist_ok=True)
        value=data if isinstance(data,bytes) else data.read();path.write_bytes(value)
        path.with_suffix(path.suffix+'.json').write_text(json.dumps({'type':content_type,'metadata':metadata or {}}),encoding='utf-8')
        return StorageObjectMetadata(key,len(value),content_type,'test-etag',metadata or {})
    def download(self,key):return self.path(key).read_bytes()
    def exists(self,key):return self.path(key).is_file()
    def delete(self,key):
        p=self.path(key);p.unlink(missing_ok=True);p.with_suffix(p.suffix+'.json').unlink(missing_ok=True)
    def get_metadata(self,key):
        p=self.path(key);meta=json.loads(p.with_suffix(p.suffix+'.json').read_text())
        return StorageObjectMetadata(key,p.stat().st_size,meta['type'],'test-etag',meta['metadata'])
    def create_presigned_url(self,key,*,expires_in=None):return '/api/v1/assets/not-a-production-url'
    def check_health(self):pass


def isolated_minio_storage():
    import boto3
    from botocore.config import Config
    from app.core.config import Settings
    from app.services.storage_service import S3StorageService
    settings=Settings(_env_file=None,environment='test',s3_bucket='agent-company-test')
    client=boto3.client('s3',endpoint_url='http://127.0.0.1:19387',aws_access_key_id='company-test',
        aws_secret_access_key='isolated-minio-test-only',region_name='us-east-1',
        config=Config(proxies={},s3={'addressing_style':'path'}))
    existing=client.list_buckets()['Buckets']
    if not any(b['Name']==settings.s3_bucket for b in existing):client.create_bucket(Bucket=settings.s3_bucket)
    return S3StorageService(settings,client=client)


def mock_understanding(filename):
    return {'role':'template' if filename.startswith('template') else 'garment','confidence':.95,
        'template_type':'gift_scene' if 'gift' in filename else 'pure_white','view':'front',
        'protected_elements':['构图与背景'] if filename.startswith('template') else ['保留当前服装图案与号码'],
        'allowed_changes':['目标服装'],'visual_facts':['仅测试素材 '+filename],'uncertainties':[]}


def install_mock_worker(ctx,monkeypatch):
    from app.workers.tasks import jobs as worker
    from app.providers.base import ProviderResult,ProviderOutput
    from tests.test_batch_tryon_workflow import PNG
    class Provider:
        async def execute(self,**kwargs):
            import asyncio
            if kwargs['capability']=='text_generation':
                payload=kwargs['payload'];meta=payload.get('metadata') or {}
                if meta.get('workflow')=='agent_creative_suggestions':
                    return ProviderResult([],provider_request_id='mock-suggestions-not-real-inference',
                        metadata={'text':json.dumps(ctx.get('mock_suggestions',{}),ensure_ascii=False),'mock_provider':True})
                if meta.get('workflow')=='agent_asset_understanding':
                    filename=json.loads(payload['user_prompt'])['filename'];understanding=mock_understanding(filename)
                    if meta.get('analysis_mode')=='template_first' and (meta.get('assigned_role')=='template' or understanding['role']=='template'):
                        understanding['reusable_prompt']='保留模板 '+filename+' 的人物、构图、背景和文字，只替换目标服装；当前图B决定每件服装的颜色、结构、图案、Logo和号码，不继承首件服装设计。'
                    return ProviderResult([],provider_request_id='mock-vision-not-real-inference',metadata={'text':json.dumps(understanding,ensure_ascii=False),'mock_provider':True})
                if ctx.get('mock_decision'):
                    decision=ctx['mock_decision']
                    return ProviderResult([],provider_request_id='mock-planner-not-real-inference',metadata={'text':json.dumps(decision,ensure_ascii=False),'mock_provider':True})
                return ProviderResult([],metadata={'text':'{}'},provider_request_id='mock-text-no-inference')
            ctx['provider_active']=ctx.get('provider_active',0)+1
            ctx['provider_max_active']=max(ctx.get('provider_max_active',0),ctx['provider_active'])
            try:
                if ctx.get('provider_release') is not None:
                    await asyncio.wait_for(ctx['provider_release'].wait(),timeout=600)
                await asyncio.sleep(ctx.get('provider_delay',.01))
                return ProviderResult([ProviderOutput(PNG,'image/png','mock-company.png')],provider_request_id='mock-image-no-real-generation',metadata={'mock_provider':True})
            finally:ctx['provider_active']-=1
    for name,value in [('get_settings',lambda:ctx['settings']),('get_engine',lambda:ctx['engine']),
        ('get_redis_client',lambda:ctx['redis']),('get_storage_service',lambda:ctx['storage'])]:monkeypatch.setattr(worker,name,value)
    monkeypatch.setattr(worker,'get_provider_adapter',lambda *a:Provider())
    return worker
