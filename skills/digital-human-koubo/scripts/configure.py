#!/usr/bin/env python3
"""Write a machine-local configuration without changing ComfyUI or downloading models."""
import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent.parent
REPO = HERE.parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--comfy-root', required=True, type=Path)
    parser.add_argument('--python', required=True, type=Path, help='Python executable that runs your existing ComfyUI')
    parser.add_argument('--workspace', type=Path, default=REPO / 'work')
    parser.add_argument('--asr-model', type=Path)
    parser.add_argument('--url', default='http://127.0.0.1:8191')
    parser.add_argument('--ffmpeg', default='ffmpeg')
    parser.add_argument('--ffprobe', default='ffprobe')
    parser.add_argument('--out', type=Path, default=HERE / 'config/local.json')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    if args.out.exists() and not args.force:
        parser.error('Configuration exists; use a new --out or --force intentionally')
    if not (args.comfy_root / 'main.py').is_file() or not args.python.is_file():
        parser.error('Existing ComfyUI main.py and its Python executable are required')
    config = dict(workspace=str(args.workspace.resolve()), comfy_root=str(args.comfy_root.resolve()),
                  python=str(args.python.resolve()), runner='../scripts/local_media.py', templates='../workflows',
                  url=args.url, observe_urls=[], image_steps=40, startup_timeout=300, job_timeout=28800,
                  poll_seconds=3, max_idle_gpu_mib=2500, ffmpeg=args.ffmpeg, ffprobe=args.ffprobe)
    # Runner/workflow paths remain relative even when --out is outside the skill.
    import os
    def portable(target):
        try: return os.path.relpath(target, args.out.resolve().parent).replace('\\', '/')
        except ValueError: return str(target.resolve())  # Different Windows drives.
    config['runner'] = portable(HERE / 'scripts/local_media.py')
    config['templates'] = portable(HERE / 'workflows')
    if args.asr_model:
        if not args.asr_model.exists(): parser.error('ASR model path does not exist')
        config['asr_model'] = str(args.asr_model.resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.workspace.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Saved machine-local config:', args.out.resolve())
    print('Next:', sys.executable, '-X utf8', HERE / 'scripts/local_media.py', '--config', args.out, 'doctor')


if __name__ == '__main__': main()
