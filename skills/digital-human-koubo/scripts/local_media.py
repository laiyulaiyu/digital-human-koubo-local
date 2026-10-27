"""Bundled project-scoped native ComfyUI runner; no cloud services.

Adapted from the installed shuohao-local-media executor. See licenses/ for
retained Apache-2.0 notices. Local release changes: portable configuration,
workflow-based environment checks, and a CLI limited to local media tasks.
"""
import argparse
import contextlib
import hashlib
import json
import math
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
ROOT = SKILL.parents[1]
DEFAULT_CONFIG = SKILL / 'config/local.json'


def read(path):
    return json.loads(Path(path).read_text('utf-8-sig'))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def output_path(path, config):
    path = Path(path).resolve()
    if not path.is_relative_to(Path(config['workspace']).resolve()):
        raise ValueError('Generated files must stay inside workspace: ' + str(path))
    return path


def request(url, method='GET', body=None, raw=False, timeout=30, headers=None):
    if body is not None and not isinstance(body, bytes):
        body = json.dumps(body).encode()
        headers = {**(headers or {}), 'Content-Type': 'application/json'}
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    # POST is deliberately not retried: a lost response may still mean accepted.
    with opener.open(req, timeout=timeout) as response:
        return response.read() if raw else json.load(response)


def node(kind, **inputs):
    return dict(class_type=kind, inputs=inputs)


def image_graph(prompt, negative, names, width, height, seed, prefix, config):
    templates = Path(config['templates']) / 'api'
    graph = read(templates / ('Qwen21-图生图.api.json' if names else 'Qwen21-文生图.api.json'))
    cin = graph['5']['inputs']
    cin.update(prompt=prompt, negative_prompt=negative, resolution=0)
    cin.pop('images.image_1', None)
    graph.pop('4', None)
    if names:
        graph.pop('6', None)
        cin.pop('images', None)
        for index, name in enumerate(names, 1):
            key = str(40 + index)
            graph[key] = node('LoadImage', image=name)
            cin['images.image_' + str(index)] = [key, 0]
        graph['7']['inputs']['latent_image'] = ['5', 2]
    else:
        cin['images'] = {}
        graph['6']['inputs'].update(width=width, height=height)
    graph['7']['inputs'].update(seed=seed, steps=config['image_steps'], cfg=1.0)
    graph['9']['inputs']['filename_prefix'] = prefix
    return graph


def frame_count(seconds):
    count = max(5, math.ceil(float(seconds) * 24 - 1e-9))
    return count + (5 - count % 17) % 17


def video_graph(prompt, first, last, refs, guides, seconds, width, height, seed, prefix, turbo, config):
    reference = bool(refs)
    name = ('H3-参考图生视频-' if reference else 'H3-首帧图生视频-')
    name += ('Turbo4步' if reference else 'Turbo8步') if turbo else '20步'
    graph = read(Path(config['templates']) / 'api' / (name + '.api.json'))
    graph.pop('20', None)
    cin = graph['5']['inputs']
    for field in list(cin):
        if field.startswith('ref_images.') or field in ['first_frame', 'last_frame']:
            del cin[field]
    cin.update(prompt=prompt, width=width, height=height, length=frame_count(seconds))
    for index, name in enumerate(refs):
        key = str(40 + index)
        graph[key] = node('LoadImage', image=name)
        cin['ref_images.ref_image_' + str(index)] = [key, 0]
    for key, field, name in [('20', 'first_frame', first), ('21', 'last_frame', last)]:
        if name and not reference:
            graph[key] = node('LoadImage', image=name)
            cin[field] = [key, 0]
    chain = ['5', 0]
    anchors = list(guides)
    if reference and first:
        anchors.insert(0, (0, first))
    if reference and last:
        anchors.append(((cin['length'] - 1) / 24, last))
    seen = set()
    for i, (seconds_at, name) in enumerate(anchors):
        frame = round(float(seconds_at) * 24)
        if frame < 0 or frame >= cin['length']:
            raise ValueError('Guide is outside video: ' + str(seconds_at))
        if frame in seen:
            raise ValueError('Two guide images occupy the same frame: ' + str(frame))
        seen.add(frame)
        load, guide = str(100 + i * 2), str(101 + i * 2)
        graph[load] = node('LoadImage', image=name)
        graph[guide] = node('MiniMaxH3AddGuide', positive=chain, latent=['5', 1], vae=['3', 0], image=[load, 0], frame_idx=frame)
        chain = [guide, 0]
    graph['7']['inputs']['conditioning'] = chain
    graph['8']['inputs']['noise_seed'] = seed
    graph['15']['inputs']['filename_prefix'] = prefix
    return graph


def text_arg(args, name, fallback=''):
    filename = getattr(args, name + '_file', None)
    return Path(filename).read_text('utf-8-sig') if filename else getattr(args, name, fallback)


def freeze(path, folder):
    source = Path(path).resolve()
    sha = file_hash(source)
    target = folder / (sha[:20] + source.suffix.lower())
    if target.exists():
        if file_hash(target) != sha:
            raise ValueError('Frozen input changed: ' + str(target))
    else:
        shutil.copy2(source, target)
    return dict(original=str(source), path=str(target), sha256=sha)


def prepare(args, config):
    out = output_path(args.out, config)
    prompt = text_arg(args, 'prompt')
    if not prompt.strip():
        raise ValueError('Prompt is empty')
    refs = list(args.refs or [])
    guides = []
    for guide in getattr(args, 'guide', []):
        at, path = guide.split('=', 1)
        guides.append((float(at), path))
    first, last = getattr(args, 'first', None), getattr(args, 'last', None)
    if args.command == 'video' and not (first or refs):
        raise ValueError('Video requires a first frame or reference images')
    if len(refs) > (16 if args.command == 'image' else 9):
        raise ValueError('More reference images than native node slots')
    sizes = {'2:3': (768, 1152), '4:5': (768, 960), '1:1': (1024, 1024), '16:9': (1152, 640), '9:16': (640, 1152)}
    ratio = getattr(args, 'ratio', None)
    if args.width and args.height:
        width, height = args.width, args.height
    elif ratio:
        width, height = sizes[ratio]
    elif args.command == 'image' and refs:
        from PIL import Image
        with Image.open(refs[0]) as im:
            width, height = im.size
    else:
        width, height = (1024, 1024) if args.command == 'image' else (1152, 640)
    width, height = max(32, round(width / 32) * 32), max(32, round(height / 32) * 32)
    inputs = refs + ([first] if first else []) + ([last] if last else []) + [p for at, p in guides]
    specification = dict(kind=args.command, prompt=prompt, negative=text_arg(args, 'negative'), width=width, height=height, seed=args.seed,
                         inputs=[dict(path=str(Path(p).resolve()), sha256=file_hash(p)) for p in inputs],
                         first=str(Path(first).resolve()) if first else None, last=str(Path(last).resolve()) if last else None,
                         references=[str(Path(p).resolve()) for p in refs],
                         seconds=getattr(args, 'seconds', None), guide_times=[at for at, p in guides], turbo=getattr(args, 'turbo', False),
                         config=digest(config))
    if args.command == 'video' and (not math.isfinite(args.seconds) or args.seconds <= 0):
        raise ValueError('Duration must be a positive finite number')
    signature = digest(specification)
    jobs = Path(config['workspace']) / 'runtime/jobs'
    jobs.mkdir(parents=True, exist_ok=True)
    if not args.new:
        for path in jobs.glob('*/job.json'):
            old = read(path)
            if old['signature'] == signature:
                old['out'] = str(out)
                save(path, old)
                return path, old
    jid = str(uuid.uuid4())
    folder = jobs / jid
    frozen_dir = folder / 'inputs'
    frozen_dir.mkdir(parents=True)
    frozen = {str(Path(p).resolve()): freeze(p, frozen_dir) for p in inputs}
    seed = args.seed if args.seed is not None else secrets.randbits(48)
    input_root = Path(config['workspace']) / 'runtime/comfy-input'
    input_root.mkdir(parents=True, exist_ok=True)
    names = {}
    for source, item in frozen.items():
        path = Path(item['path'])
        name = 'jobs/' + jid + '/' + path.name
        dest = input_root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        names[source] = name
    image_names = [names[str(Path(p).resolve())] for p in refs]
    if args.command == 'image' and image_names:
        from PIL import Image, ImageOps
        # Keep the approved source intact; fit a conditioning copy without stretching.
        with Image.open(frozen[str(Path(refs[0]).resolve())]['path']) as im:
            target = ImageOps.pad(im.convert('RGB'), (width, height), color='white', method=Image.Resampling.LANCZOS)
            name = 'jobs/' + jid + '/canvas-reference.png'
            target.save(input_root / name)
            image_names[0] = name
    prefix = 'jobs/' + jid + '/output'
    if args.command == 'image':
        graph = image_graph(prompt, specification['negative'], image_names, width, height, seed, prefix, config)
    else:
        get_name = lambda p: names[str(Path(p).resolve())] if p else None
        graph = video_graph(prompt, get_name(first), get_name(last), image_names, [(at, get_name(p)) for at, p in guides], args.seconds, width, height, seed, prefix, args.turbo, config)
    execution_inputs = [dict(path=str(input_root / n['inputs']['image']), sha256=file_hash(input_root / n['inputs']['image'])) for n in graph.values() if n['class_type'] == 'LoadImage']
    record = dict(id=jid, signature=signature, state='prepared', kind=args.command, seed=seed, out=str(out), specification=specification, execution_inputs=execution_inputs,
                  inputs=list(frozen.values()), graph_sha256=digest(graph), graph='graph.api.json', created_at=time.time(), comfy_url=config['url'])
    save(folder / 'graph.api.json', graph)
    save(folder / 'job.json', record)
    return folder / 'job.json', record


@contextlib.contextmanager
def execution_lock(config):
    path = Path(config['workspace']) / 'runtime/generation.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as f:
        f.seek(0, 2)
        if not f.tell():
            f.write(b'0'); f.flush()
        f.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            f.seek(0)
            if os.name == 'nt':
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f, fcntl.LOCK_UN)


def process_command(pid):
    if os.name != 'nt':
        return Path('/proc/' + str(pid) + '/cmdline').read_text()
    code = '[Console]::OutputEncoding = [Text.UTF8Encoding]::new(); ' + f'(Get-CimInstance Win32_Process -Filter "ProcessId={int(pid)}").CommandLine'
    return subprocess.run(['powershell', '-NoProfile', '-Command', code], capture_output=True, text=True, encoding='utf-8', errors='strict', check=True).stdout


def server(config, action):
    root = Path(config['workspace'])
    (root / 'logs').mkdir(parents=True, exist_ok=True)
    ledger = root / 'runtime/server.json'
    owned = read(ledger) if ledger.exists() else None
    if action == 'status':
        return dict(owned=owned, stats=request(config['url'] + '/system_stats'))
    if action == 'stop':
        if not owned or owned.get('state') != 'running':
            return dict(state='already_stopped')
        pid = owned['pid']
        if owned['instance_token'] not in process_command(pid):
            raise RuntimeError('Owned server process identity no longer matches')
        q = request(config['url'] + '/queue')
        if q['queue_running'] or q['queue_pending']:
            raise RuntimeError('Server still has queued work; left running')
        os.kill(pid, 15)
        owned['state'] = 'stopped'
        save(ledger, owned)
        return owned
    parsed = urllib.parse.urlsplit(config['url'])
    try:
        with socket.create_connection((parsed.hostname, parsed.port), timeout=1):
            if owned and owned.get('state') == 'running' and owned['instance_token'] in process_command(owned['pid']):
                return owned
            raise RuntimeError('Dedicated port is occupied by an unowned server')
    except (ConnectionRefusedError, socket.timeout):
        pass
    instance = root / 'runtime' / ('comfy-' + uuid.uuid4().hex[:10])
    user = instance / 'user'
    user.mkdir(parents=True)
    for folder in ['comfy-input', 'comfy-output', 'comfy-temp']:
        (root / 'runtime' / folder).mkdir(exist_ok=True)
    cmd = [config['python'], '-s', str(Path(config['comfy_root']) / 'main.py'), '--lowvram', '--disable-auto-launch', '--disable-assets', '--disable-api-nodes', '--disable-all-custom-nodes',
           '--listen', parsed.hostname, '--port', str(parsed.port), '--input-directory', str(root / 'runtime/comfy-input'), '--output-directory', str(root / 'runtime/comfy-output'),
           '--temp-directory', str(root / 'runtime/comfy-temp'), '--user-directory', str(user)]
    with (root / 'logs/comfy.log').open('ab') as log:
        p = subprocess.Popen(cmd, cwd=config['comfy_root'], stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    owned = dict(pid=p.pid, state='running', instance_token=str(instance), command=cmd, url=config['url'])
    save(ledger, owned)
    end = time.monotonic() + config['startup_timeout']
    while time.monotonic() < end:
        if p.poll() is not None:
            owned['state'] = 'failed'; save(ledger, owned)
            raise RuntimeError('ComfyUI exited; see logs/comfy.log')
        try:
            request(config['url'] + '/system_stats', timeout=2)
            return owned
        except (urllib.error.URLError, TimeoutError):
            time.sleep(1)
    raise TimeoutError('Server startup timeout; process record retained')


def check_idle(config):
    for url in [config['url']] + config.get('observe_urls', []):
        try:
            q = request(url + '/queue', timeout=3)
        except urllib.error.URLError as e:
            if isinstance(e.reason, ConnectionRefusedError) or getattr(e.reason, 'winerror', None) == 10061:
                continue
            raise
        if q.get('queue_running') or q.get('queue_pending'):
            raise RuntimeError('GPU server has queued work: ' + url)
    def used_memory():
        result = subprocess.run(['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits'], capture_output=True, text=True, check=True)
        return int(result.stdout.strip().splitlines()[0])

    if used_memory() <= config['max_idle_gpu_mib']:
        return
    # A completed job can leave our own models cached on the GPU. Only release
    # this runner's verified, idle server; other servers' caches stay untouched.
    ledger = Path(config['workspace']) / 'runtime/server.json'
    owned = read(ledger) if ledger.exists() else None
    if (owned and owned.get('state') == 'running' and owned.get('url') == config['url']
            and owned['instance_token'] in process_command(owned['pid'])):
        request(config['url'] + '/free', 'POST', dict(unload_models=True, free_memory=True), raw=True)
        for _ in range(15):
            time.sleep(1)
            if used_memory() <= config['max_idle_gpu_mib']:
                return
    raise RuntimeError('GPU memory is occupied; no job submitted')


def find_prompt(config, jid):
    history = request(config['url'] + '/history/' + jid)
    if jid in history:
        return 'history', history[jid]
    q = request(config['url'] + '/queue')
    for row in q.get('queue_running', []) + q.get('queue_pending', []):
        if row[1] == jid:
            return 'queue', row
    return None, None


def verify_artifact(path, kind, record, config):
    if kind == 'image':
        from PIL import Image
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            if im.size != (record['specification']['width'], record['specification']['height']):
                raise RuntimeError('Image dimensions differ from planned canvas')
            return dict(width=im.width, height=im.height)
    result = subprocess.run([config['ffprobe'], '-v', 'error', '-count_frames', '-show_streams', '-show_format', '-of', 'json', str(path)], capture_output=True, text=True, encoding='utf-8', check=True)
    info = json.loads(result.stdout)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    audio = next((s for s in info['streams'] if s['codec_type'] == 'audio'), None)
    expected = frame_count(record['specification']['seconds'])
    if int(video['nb_read_frames']) != expected or not audio:
        raise RuntimeError('Video frame count or original audio stream is missing')
    rate_num, rate_den = map(int, video['avg_frame_rate'].split('/'))
    if abs(rate_num / rate_den - 24) > .001:
        raise RuntimeError('Video frame rate is not 24fps')
    if abs(float(info['format']['duration']) - expected / 24) > .15:
        raise RuntimeError('Container duration differs from planned frame duration')
    if (video['width'], video['height']) != (record['specification']['width'], record['specification']['height']):
        raise RuntimeError('Video dimensions differ from plan')
    subprocess.run([config['ffmpeg'], '-v', 'error', '-i', str(path), '-f', 'null', '-'], capture_output=True, check=True)
    return dict(width=video['width'], height=video['height'], frames=expected, seconds=float(info['format']['duration']), audio_sample_rate=audio['sample_rate'], full_decode=True, visual_review='pending', subjective_listening='pending')


def write_output(job_path, record, config):
    artifact = Path(record['artifact'])
    out = output_path(record['out'], config)
    if out.suffix.lower() != artifact.suffix.lower():
        raise ValueError('Requested output suffix differs from generated container: ' + artifact.suffix)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(artifact, out)
    save(out.with_suffix(out.suffix + '.job.json'), dict(job_id=record['id'], job=str(job_path), sha256=record['artifact_sha256'], qc=record['qc'], graph_sha256=record['graph_sha256']))


def collect(job_path, record, history, config):
    output_key = '9' if record['kind'] == 'image' else '15'
    output = history.get('outputs', {}).get(output_key, {})
    files = [f for field in ['images', 'gifs', 'videos'] for f in output.get(field, []) if f.get('type') == 'output']
    suffixes = ['.png'] if record['kind'] == 'image' else ['.mp4', '.webm', '.mkv']
    file = next((f for f in files if Path(f['filename']).suffix.lower() in suffixes), None)
    if not file:
        raise RuntimeError('ComfyUI history has no matching output file')
    data = request(config['url'] + '/view?' + urllib.parse.urlencode({k: file[k] for k in ['filename', 'subfolder', 'type']}), raw=True, timeout=300)
    artifact = job_path.parent / ('artifact' + Path(file['filename']).suffix.lower())
    artifact.write_bytes(data)
    qc = verify_artifact(artifact, record['kind'], record, config)
    record.update(state='succeeded', artifact=str(artifact), artifact_sha256=file_hash(artifact), qc=qc, completed_at=time.time())
    write_output(job_path, record, config)
    save(job_path, record)
    save(job_path.parent / 'history.json', history)
    return record


def execute(job_path, record, config):
    with execution_lock(config):
        for item in record['inputs'] + record['execution_inputs']:
            if file_hash(item['path']) != item['sha256']:
                raise ValueError('Frozen input hash changed')
        graph = read(job_path.parent / record['graph'])
        if digest(graph) != record['graph_sha256']:
            raise ValueError('Recorded graph changed')
        if record['state'] == 'succeeded':
            artifact = Path(record['artifact'])
            if file_hash(artifact) != record['artifact_sha256']:
                raise ValueError('Completed artifact changed')
            write_output(job_path, record, config)
            return record
        server(config, 'start')
        state, data = find_prompt(config, record['id'])
        if not state:
            if record['state'] in ['submitting', 'submitted', 'uncertain', 'waiting']:
                raise RuntimeError('Previous submission outcome is unknown. No duplicate submitted; inspect server history or use --new intentionally.')
            if record['state'] == 'failed':
                raise RuntimeError('Previous job failed; inspect saved error and use --new for another attempt')
            check_idle(config)
            record['state'] = 'submitting'; save(job_path, record)
            try:
                answer = request(config['url'] + '/prompt', 'POST', dict(prompt_id=record['id'], prompt=graph, client_id='shuohao-local', extra_data={'shuohao_job': record['id']}))
                if answer['prompt_id'] != record['id']:
                    raise RuntimeError('Server returned another prompt id')
                record['state'] = 'submitted'; save(job_path, record)
            except urllib.error.HTTPError as e:
                record.update(state='failed', error=e.read().decode('utf-8', 'replace')); save(job_path, record)
                raise
            except Exception as e:
                record.update(state='uncertain', error=str(e)); save(job_path, record)
                raise
        deadline = time.monotonic() + config['job_timeout']
        last_error = None
        while time.monotonic() < deadline:
            try:
                history = request(config['url'] + '/history/' + record['id'])
                result = history.get(record['id'])
                if result and result.get('status', {}).get('status_str') == 'error':
                    record.update(state='failed', error=result['status']); save(job_path, record)
                    raise RuntimeError('Generation failed; see recorded execution_error')
                if result and result.get('status', {}).get('completed'):
                    return collect(job_path, record, result, config)
            except (urllib.error.URLError, TimeoutError) as e:
                last_error = str(e)
            time.sleep(config['poll_seconds'])
        record.update(state='waiting', error=last_error or 'Polling timeout; job may still be running'); save(job_path, record)
        raise TimeoutError('Task retained. Resume with job id: ' + record['id'])


def resolve_pack_file(value, manifest):
    p = Path(value)
    candidates = [p] if p.is_absolute() else [manifest.parent / p, manifest.parent.parent / p]
    return next((p.resolve() for p in candidates if p.is_file()), None)


def run_pack(args, config):
    manifest = Path(args.manifest).resolve()
    rows = read(manifest)
    if not args.all and not args.segment:
        raise ValueError('Select --segment ID or --all')
    chosen = [r for r in rows if args.all or r['segment'] == args.segment]
    if not chosen:
        raise ValueError('No matching segment')
    records = []
    for row in chosen:
        pictures = [resolve_pack_file(p, manifest) for p in row['pictures']]
        prompt_path = resolve_pack_file(row['prompt'], manifest)
        if not pictures or any(p is None for p in pictures) or not prompt_path:
            raise FileNotFoundError('Production pack has missing pictures or prompt: ' + row['segment'])
        text = prompt_path.read_text('utf-8-sig')
        prompt = text.split('\n---\n', 1)[-1].strip()
        starts = row['cutStarts']
        if len(starts) != len(pictures) or starts[0] != 0 or any(a >= b for a, b in zip(starts, starts[1:])):
            raise ValueError('Picture/cutStarts mapping is inconsistent')
        spec = argparse.Namespace(command='video', prompt=prompt, prompt_file=None, negative='', negative_file=None, refs=[str(p) for p in pictures], first=None, last=None,
                                  guide=[str(at) + '=' + str(path) for at, path in zip(starts, pictures)], seconds=row['seconds'], width=args.width, height=args.height,
                                  ratio=None, seed=args.seed, turbo=args.turbo, out=str(Path(args.out_dir) / (row['segment'] + '.mp4')), new=args.new)
        job_path, record = prepare(spec, config)
        records.append(record if args.dry_run else execute(job_path, record, config))
    return records


def environment_report(config, online=False, profile='video'):
    import importlib.util
    groups = {'video': ['H3-首帧图生视频-20步'], 'image': ['Qwen21-文生图'],
              'all': ['H3-首帧图生视频-20步', 'H3-首帧图生视频-Turbo8步',
                      'H3-参考图生视频-20步', 'H3-参考图生视频-Turbo4步', 'Qwen21-文生图']}
    roles = {'UNETLoader': ('diffusion_models', 'unet_name'), 'CLIPLoader': ('text_encoders', 'clip_name'),
             'VAELoader': ('vae', 'vae_name'), 'LoraLoaderModelOnly': ('loras', 'lora_name')}
    checks = {}
    for name in groups[profile]:
        for entry in read(Path(config['templates']) / 'api' / (name + '.api.json')).values():
            if entry['class_type'] in roles:
                folder, field = roles[entry['class_type']]
                path = Path(config['comfy_root']) / 'models' / folder / entry['inputs'][field]
                checks[str(path)] = path.is_file()
    programs = {key: bool(shutil.which(config[key]) or Path(config[key]).is_file())
                for key in ('python', 'ffmpeg', 'ffprobe')}
    programs['node'] = shutil.which('node') is not None
    packages = {name: importlib.util.find_spec(name) is not None for name in ('numpy', 'PIL', 'faster_whisper')}
    from local_asr import find_model
    try:
        asr = config.get('asr_model') or str(find_model())
        asr_ok = Path(asr).exists()
    except FileNotFoundError:
        asr, asr_ok = None, False
    report = dict(profile=profile, models=checks, programs=programs, packages=packages,
                  asr_model=asr, asr_model_present=asr_ok, generated=False)
    if online:
        report['stats'] = request(config['url'] + '/system_stats')
        info = request(config['url'] + '/object_info')
        required = ['MiniMaxH3ImageToVideo', 'CreateVideo', 'SaveVideo', 'VAEDecodeAudio']
        if profile in ('all', 'image'): required += ['TextEncodeQwenImage21']
        if profile == 'all': required += ['MiniMaxH3ReferenceToVideo', 'MiniMaxH3AddGuide']
        report['missing_nodes'] = [name for name in required if name not in info]
    report['ok'] = (all(checks.values()) and all(programs.values()) and all(packages.values())
                    and asr_ok and not report.get('missing_nodes'))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(DEFAULT_CONFIG))
    sub = parser.add_subparsers(dest='command', required=True)
    doctor = sub.add_parser('doctor'); doctor.add_argument('--online', action='store_true')
    doctor.add_argument('--profile', choices=['video', 'image', 'all'], default='video')
    srv = sub.add_parser('server'); srv.add_argument('action', choices=['start', 'stop', 'status'])
    init = sub.add_parser('init'); init.add_argument('name')
    resume = sub.add_parser('resume'); resume.add_argument('id')
    for kind in ['image', 'video']:
        p = sub.add_parser(kind)
        p.add_argument('--width', type=int); p.add_argument('--height', type=int)
        p.add_argument('--seed', type=lambda v: int(v) if v else None)
        p.add_argument('--new', action='store_true'); p.add_argument('--dry-run', action='store_true')
        if kind == 'pack':
            p.add_argument('--manifest', required=True); p.add_argument('--segment'); p.add_argument('--all', action='store_true')
            p.add_argument('--out-dir', required=True); p.add_argument('--turbo', action='store_true')
            continue
        text = p.add_mutually_exclusive_group(required=True)
        text.add_argument('--prompt'); text.add_argument('--prompt-file')
        p.add_argument('--negative', default=''); p.add_argument('--negative-file')
        p.add_argument('--refs', nargs='*', default=[])
        p.add_argument('--ratio', choices=['2:3', '4:5', '1:1', '16:9', '9:16'])
        p.add_argument('--out', required=True)
        if kind == 'video':
            p.add_argument('--first'); p.add_argument('--last'); p.add_argument('--guide', action='append', default=[])
            p.add_argument('--seconds', type=float, default=5); p.add_argument('--turbo', action='store_true')
    args = parser.parse_args(argv)
    from local_config import load
    config = load(args.config)
    if args.command == 'doctor':
        result = environment_report(config, args.online, args.profile)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['ok'] else 1
    elif args.command == 'server':
        result = server(config, args.action)
    elif args.command == 'init':
        if Path(args.name).name != args.name or args.name in ['.', '..']:
            raise ValueError('Project name must be a single folder name')
        target = output_path(Path(config['workspace']) / 'projects' / args.name, config)
        target.mkdir(parents=True, exist_ok=False)
        for name in ['story', 'assets', 'storyboard', 'images', 'videos', 'final', 'reports']:
            (target / name).mkdir()
        save(target / 'project.json', dict(name=args.name, created_at=time.time(), root=str(target)))
        result = dict(project=str(target))
    elif args.command == 'resume':
        uuid.UUID(args.id)
        path = Path(config['workspace']) / 'runtime/jobs' / args.id / 'job.json'
        result = execute(path, read(path), config)
    elif args.command == 'pack':
        result = run_pack(args, config)
    else:
        path, record = prepare(args, config)
        result = record if args.dry_run else execute(path, record, config)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        print(type(e).__name__ + ': ' + str(e), file=sys.stderr)
        sys.exit(1)
