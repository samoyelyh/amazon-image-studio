import hashlib
import json
from pathlib import Path
from app.services.storage_service import StorageService, StorageObjectMetadata


class ExperimentStorage(StorageService):
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key):
        target = (self.root / key).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError('Storage path escapes the experiment')
        return target

    def upload(self, key, data, *, content_type, metadata=None):
        target = self.path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        content = data if isinstance(data, bytes) else data.read()
        temp = target.with_suffix(target.suffix + '.tmp')
        temp.write_bytes(content)
        temp.replace(target)
        target.with_suffix(target.suffix + '.json').write_text(json.dumps({'content_type': content_type, 'metadata': metadata or {}}), encoding='utf-8')
        return self.get_metadata(key)

    def download(self, key):
        return self.path(key).read_bytes()

    def delete(self, key):
        self.path(key).unlink(missing_ok=True)
        self.path(key).with_suffix(self.path(key).suffix + '.json').unlink(missing_ok=True)

    def exists(self, key):
        return self.path(key).is_file()

    def get_metadata(self, key):
        content = self.path(key).read_bytes()
        meta = json.loads(self.path(key).with_suffix(self.path(key).suffix + '.json').read_text(encoding='utf-8'))
        return StorageObjectMetadata(key, len(content), meta['content_type'], hashlib.sha256(content).hexdigest(), meta['metadata'])

    def create_presigned_url(self, key, *, expires_in=None):
        # Downloads use the original authenticated /assets/{id}/content endpoint.
        return '/api/v1/experiment/files-require-authentication'

    def check_health(self):
        if not self.root.is_dir():
            raise RuntimeError('Experiment storage unavailable')
