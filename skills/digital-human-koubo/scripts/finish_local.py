#!/usr/bin/env python3
"""Orchestrate the ORIGINAL assemble/align/voicefx/check scripts for local clips.

This is a cross-platform entry point, not an alternate editing implementation.
Run only after inspecting generated clips. Remotion rendering remains unchanged.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from local_backend import read

SCRIPTS = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project')
    parser.add_argument('--edit', default='edit')
    args = parser.parse_args()
    root = Path(args.project).resolve()
    env = os.environ.copy()
    if (root / 'tasks.json').is_file():
        from local_config import load
        cfg = load(read(root / 'tasks.json')['config'])
        if cfg.get('asr_model'): env.setdefault('DH_ASR_MODEL', cfg['asr_model'])
        tool_dirs = [str(Path(cfg[k]).parent) for k in ('ffmpeg', 'ffprobe') if Path(cfg[k]).is_absolute()]
        env['PATH'] = os.pathsep.join(tool_dirs + [env.get('PATH', '')])
    edit = Path(args.edit)
    edit = edit.resolve() if edit.is_absolute() else (root / edit).resolve()
    rows = read(root / 'script.json')
    ids = read(root / 'ids.json')
    if any(ids.get(row['id'], {}).get('state') != 'succeeded' for row in rows):
        parser.error('Every local segment must have succeeded before finishing')
    if not (edit / 'src/edit.json').is_file():
        parser.error('Initialize an original template with new_edit.py first')
    def original(name, *arguments):
        subprocess.run([sys.executable, '-X', 'utf8', str(SCRIPTS / name), *map(str, arguments)], cwd=root, env=env, check=True)
    original('assemble.py', 'script.json', 'ids.json', '--out', edit / 'public/main.mp4')
    original('align.py', 'script.json', '--out', edit / 'src/tl.json')
    clips = [root / 'cut' / (row['id'] + '.mp4') for row in rows]
    original('voicefx/unify.py', root / 'voice', *clips)
    # Segment ids are already constrained by build_tasks. Relative paths keep ffconcat
    # independent of non-ASCII Windows drive paths and require no shell escaping.
    listing = root / 'voice/list.txt'
    listing.write_text(''.join("file '" + row['id'] + ".wav'\n" for row in rows), encoding='utf-8')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(listing),
                    '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', str(edit / 'public/voice.wav')], cwd=root, env=env, check=True)
    original('check_edit.py', edit / 'src')
    timeline = read(edit / 'src/tl.json')
    durations = {}
    for filename in ('main.mp4', 'voice.wav'):
        durations[filename] = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                                           '-of', 'csv=p=0', str(edit / 'public' / filename)], env=env, text=True).strip())
    if any(abs(length - timeline['total']) > 0.1 for length in durations.values()):
        raise RuntimeError('AV duration differs from aligned timeline: ' + json.dumps(durations))
    print('Original pipeline completed:', timeline['total'], 'seconds', durations)
    print('Inspect source clips and rendered intermediate frames; ASR pass alone is not perceptual approval.')


if __name__ == '__main__':
    main()
