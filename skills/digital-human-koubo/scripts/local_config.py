"""Portable, config-file-relative paths for the bundled local backend."""
import json
import os
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent.parent
DEFAULT = HERE / 'config/local.json'


def load(path=None):
    path = Path(path or os.environ.get('DH_LOCAL_CONFIG', DEFAULT)).expanduser().resolve()
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    defaults = {'runner': str(HERE / 'scripts/local_media.py'), 'templates': str(HERE / 'workflows'),
                'image_steps': 40, 'startup_timeout': 300, 'job_timeout': 28800, 'poll_seconds': 3,
                'max_idle_gpu_mib': 2500, 'url': 'http://127.0.0.1:8191', 'observe_urls': [],
                'python': sys.executable, 'ffmpeg': 'ffmpeg', 'ffprobe': 'ffprobe'}
    config = defaults | config
    for key in ('workspace', 'comfy_root', 'runner', 'templates', 'asr_model'):
        if config.get(key):
            expanded = os.path.expanduser(os.path.expandvars(config[key]))
            value = Path(expanded)
            # Preserve existing absolute spellings so old task hashes remain valid.
            config[key] = expanded if value.is_absolute() else str((path.parent / value).resolve())
    for key in ('python', 'ffmpeg', 'ffprobe'):
        value = os.path.expandvars(config[key])
        if '/' in value or '\\' in value:
            executable = Path(value).expanduser()
            config[key] = value if executable.is_absolute() else str((path.parent / executable).resolve())
        else:
            config[key] = shutil.which(value) or value
    return config
