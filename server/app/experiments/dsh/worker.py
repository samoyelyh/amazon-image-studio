from app.experiments.dsh.environment import configure, STATE
configure()
from app.services import storage_service
from app.experiments.dsh.storage import ExperimentStorage
storage = ExperimentStorage(STATE / 'objects')
storage_service.get_storage_service = lambda: storage
from app.experiments.dsh.ledger import install_guards
install_guards(STATE / 'worker')
from app.workers.celery_app import celery_app
celery_app.conf.broker_transport_options = {**celery_app.conf.broker_transport_options, 'global_keyprefix':'dsh-experiment:'}

if __name__ == '__main__':
    import sys
    celery_app.worker_main(['worker','--pool=solo','--concurrency=1','--loglevel=WARNING','--without-gossip','--without-mingle',
        '--hostname=dsh-experiment-'+sys.argv[1]+'@%h','--queues=planning_queue,listing_queue,aplus_queue,batch_tryon_queue,default'])
