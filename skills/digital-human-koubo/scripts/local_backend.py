#!/usr/bin/env python3
"""ComfyUI adapter for the existing koubo script -> assemble -> align -> Remotion flow.

Uses the bundled executor (adapted from shuohao-local-media) for submission,
input hashes, progress and resume; an external runner override remains optional.
No model downloads, cloud calls or alternate editing engine.
"""
import argparse
import importlib.util
import json
import math
import os
import re
import sys
from pathlib import Path
from local_config import load as load_config

HERE = Path(__file__).resolve().parent.parent


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def config_path(value=None):
    path = Path(value or os.environ.get('DH_LOCAL_CONFIG', HERE / 'config/local.json')).resolve()
    if not path.is_file():
        raise FileNotFoundError('Pass --config or DH_LOCAL_CONFIG; see config/local.example.json')
    return path


def load_runner(config):
    path = Path(config['runner']).resolve()
    spec = importlib.util.spec_from_file_location('koubo_native_runner', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if config.get('local_loras'):
        from local_lora import describe_loras, add_to_graph
        loras = describe_loras(config['local_loras'], config)
        original = module.video_graph
        def video_graph(*args, **kwargs):
            return add_to_graph(original(*args, **kwargs), loras)
        module.video_graph = video_graph
    return module


def inside(value, workspace):
    path = Path(value).resolve()
    if not path.is_relative_to(Path(workspace).resolve()):
        raise ValueError('Output must stay in configured workspace: ' + str(path))
    return path


def local_file(value, root):
    if not value or str(value).startswith(('material:', 'task:', 'http:', 'https:')):
        raise ValueError('Local H3 needs a local first-frame/reference image')
    path = Path(value)
    path = path.resolve() if path.is_absolute() else (root / path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return str(path)


def prompt_for(segment, seconds, purpose):
    """H3 I2VA fields; keep supplied dialogue intact and do not seed ASR with it."""
    if segment.get('prompt'):
        return segment['prompt']
    line = segment['t']
    language = segment.get('lang', 'Mandarin Chinese')
    voice = segment.get('voice', 'a warm, steady adult female voice, medium-low pitch, clear standard Mandarin, conversational delivery')
    gestures = segment.get('gestures', [])
    delivery = 'natural lip movement and small facial gestures'
    movement = ''
    if gestures:
        previous = -1
        for beat in gestures:
            at = line.find(beat['on'])
            if not beat['on'] or at < 0 or at <= previous or not beat['action'].strip():
                raise ValueError('Gesture cues must occur in dialogue order with nonempty actions')
            previous = at
        delivery = 'natural lip movement, relaxed upper-body weight shifts and restrained conversational hand gestures'
        movement = ('Frame her from head to mid-thigh, keeping both forearms and complete hands visible. '
                    'Her shoulder and torso movements follow speech emphasis with small amplitude. '
                    'Hands return towards a relaxed waist-level position during pauses; no continuous metronomic rocking. ')
        movement += ' '.join('As she says the words ' + beat['on'] + ', she ' + beat['action'] + '.' for beat in gestures) + ' '
    return (
        'For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n'
        'integrated_multimodal_description: [Shot 1] Live-action studio talking head. '
        'Preserve the exact person, face, hairstyle, clothing, lighting and framing in the first frame. '
        'The camera holds a static shot. The sole adult presenter (S1), with ' + voice + ', '
        'looks directly into the lens and speaks with ' + delivery + ', ' + purpose + '. '
        + movement +
        f'After a brief opening breath she says exactly once: <d>[{language}] {line}</d> '
        f'She finishes the complete sentence before {seconds - 0.4:.2f} seconds, then gently closes her mouth. '
        'Keep the shot continuous. Keep the image clean, without captions, text, logos or watermarks.\n\n'
        'overall_soundscape: Quiet indoor room tone beneath clean close-microphone speech. '
        'No additional speaker or echoing speech.\n\n'
        'non_diegetic_music: N/A'
    )


def build_manifest(src, dst, cfg=None, purpose='explaining clearly'):
    cfg_path = config_path(cfg)
    config = load_config(cfg_path)
    runner = load_runner(config)
    source = Path(src).resolve()
    rows = read(source)
    if not isinstance(rows, list) or not rows:
        raise ValueError('script.json must be a nonempty segment array')
    ids, segments = set(), []
    output = inside(Path(dst).resolve().parent, config['workspace'])
    for row in rows:
        sid = row['id']
        if not re.fullmatch(r'[A-Za-z0-9_-]+', sid) or sid in ids:
            raise ValueError('Segment id must be unique and filename-safe: ' + str(sid))
        ids.add(sid)
        if not str(row.get('t', '')).strip():
            raise ValueError('Empty dialogue: ' + sid)
        # Explicit duration: Grok's empirically measured speaking speed is not H3's.
        seconds = float(row['seconds'])
        if not math.isfinite(seconds) or not 4 <= seconds <= 15:
            raise ValueError('H3 seconds must be explicitly set between 4 and 15: ' + sid)
        width, height = int(row.get('width', 448)), int(row.get('height', 800))
        if min(width, height) < 32 or width % 32 or height % 32:
            raise ValueError('H3 canvas dimensions must be positive multiples of 32')
        if row.get('mode', 'first') not in ('first', 'reference'):
            raise ValueError('mode must be first or reference')
        first = local_file(row['first'], source.parent) if row.get('first') else None
        refs = [local_file(p, source.parent) for p in row.get('refs', [])]
        if first and refs:
            raise ValueError('Use first OR refs, not both: ' + sid)
        actual_mode = 'reference' if refs else 'first'
        if row.get('mode', actual_mode) != actual_mode:
            raise ValueError('mode does not match the supplied image input: ' + sid)
        if not first and not refs:
            raise ValueError('Provide first or refs: ' + sid)
        # Ref2VA requires its own prompt format; do not silently use an I2VA prompt.
        if refs and not row.get('prompt'):
            raise ValueError('Reference mode requires an explicit Ref2VA prompt: ' + sid)
        prompt = prompt_for(row, runner.frame_count(seconds) / 24, purpose)
        loras = []
        if row.get('loras'):
            from local_lora import describe_loras
            loras = describe_loras(row['loras'], config)
        segments.append(dict(id=sid, t=row['t'], seconds=seconds, effective_seconds=runner.frame_count(seconds)/24,
                             frames=runner.frame_count(seconds), width=width, height=height, first=first,
                             refs=refs, mode='reference' if refs else 'first', seed=int(row.get('seed', 27000 + len(segments))),
                             turbo=bool(row.get('turbo', False)), prompt=prompt, loras=loras,
                             gestures=row.get('gestures', []),
                             out=str(output / 'gen' / (sid + '.mp4'))))
    result = dict(backend='comfyui', version=1, script=str(source), config=str(cfg_path), segments=segments)
    write(inside(dst, config['workspace']), result)
    print(f"{len(segments)} segments · {sum(s['effective_seconds'] for s in segments):.2f}s · local H3 · no Renoise credits")
    return result


def run_manifest(path, only=None, dry_run=False):
    path = Path(path).resolve()
    manifest = read(path)
    if manifest.get('backend') != 'comfyui':
        raise ValueError('Expected a local manifest from build_tasks.py')
    config = load_config(config_path(manifest['config']))
    root = inside(path.parent, config['workspace'])
    (Path(config['workspace']) / 'logs').mkdir(parents=True, exist_ok=True)
    ids_path = root / 'ids.json'
    mapping = read(ids_path) if ids_path.exists() else {}
    chosen = [s for s in manifest['segments'] if only is None or s['id'] in only]
    if not chosen or only and set(only) != {s['id'] for s in chosen}:
        raise ValueError('Unknown or empty segment selection')
    for segment in chosen:
        effective_config = dict(config, local_loras=segment['loras']) if segment.get('loras') else config
        runner = load_runner(effective_config)
        args = argparse.Namespace(command='video', prompt=segment['prompt'], prompt_file=None,
                                  negative='', negative_file=None, refs=segment['refs'], first=segment['first'],
                                  last=None, guide=[], seconds=segment['seconds'], width=segment['width'],
                                  height=segment['height'], ratio=None, seed=segment['seed'],
                                  turbo=segment['turbo'], out=segment['out'], new=False)
        job_path, record = runner.prepare(args, effective_config)
        entry = dict(path=segment['out'], job_id=record['id'], job=str(job_path), backend='comfyui', state=record['state'])
        # Persist BEFORE execution, so Ctrl+C/unknown POST never loses the resume id.
        mapping[segment['id']] = entry
        write(ids_path, mapping)
        print(json.dumps(entry, ensure_ascii=False), flush=True)
        if dry_run:
            continue
        try:
            record = runner.execute(job_path, record, effective_config)
        finally:
            latest = runner.read(job_path)
            entry['state'] = latest['state']
            write(ids_path, mapping)
        print(f"{segment['id']}: {record['state']} -> {segment['out']}", flush=True)
    return mapping


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    run = sub.add_parser('run')
    run.add_argument('manifest')
    run.add_argument('--only', nargs='+')
    run.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    run_manifest(args.manifest, args.only, args.dry_run)


if __name__ == '__main__':
    main()
