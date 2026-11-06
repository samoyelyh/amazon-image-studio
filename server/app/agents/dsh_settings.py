"""Deployment settings shared by the native business bridge and platform UI."""
import os
from pathlib import Path

def enabled():return os.environ.get('DSH_ENABLED','false').lower()=='true'
def state():
    from app.experiments.dsh.environment import STATE
    root=Path(os.environ.get('DSH_PLATFORM_STATE_DIR',str(STATE)))
    root.mkdir(parents=True,exist_ok=True)
    return root
def token():return os.environ.get('DSH_INTERNAL_TOKEN') or (state()/'sidecar.token').read_text().strip()
def sidecar_url():return os.environ.get('DSH_SIDECAR_URL','http://127.0.0.1:18871')
