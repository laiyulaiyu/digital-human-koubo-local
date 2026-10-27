#!/usr/bin/env python3
"""逐段回听 → 剪掉段尾空白 → 统一规格 → 拼接。
用法：python3 assemble.py script.json ids.json [--out 成片_完整版.mp4] [--lang zh] [--size 宽x高（默认保持源尺寸）]
- script.json：[{"id","t",...}]（和 build_tasks.py 同一份）；本地 ids.json 由 local_backend.py 写入 path/job_id/state；旧的 {"s1": 363509} 仍读取 gen/renoise-<taskId>.mp4
- 每段：whisper 转写（中性提示，不用 --prompt 原文，免得漏前半句）→ 和文稿比准确率 → 只保留到说完后 0.25 秒
- 输出 cut/<id>.mp4（30fps、48k 立体声）、cut/<id>.json（逐字时间，align.py 用）、cut/qa.json、拼接好的 --out（-16 LUFS）
- 准确率 < 85% 的段打 ⚠，先人工听；真念错就单独重拍那段"""
import json, subprocess, difflib, re, os, sys
from pathlib import Path
a = sys.argv[1:]
if len(a) < 2: sys.exit(__doc__)
S = json.loads(Path(a[0]).read_text(encoding='utf-8-sig')); IDS = json.loads(Path(a[1]).read_text(encoding='utf-8-sig'))
opt = lambda k, d: a[a.index(k) + 1] if k in a else d
out_name, lang, size = opt('--out', '成片_完整版.mp4'), opt('--lang', 'zh'), opt('--size', '')
clean = lambda s: re.sub(r'[\s，。、：；！？,.:;!?“”]', '', s).lower()
Path('cut').mkdir(exist_ok=True); rep = []
for s in S:
    sid = s['id']; entry = IDS[sid]
    if isinstance(entry, dict):
        if entry.get('backend') == 'comfyui' and entry.get('state') != 'succeeded':
            sys.exit(f'{sid}: local generation is not complete; resume it first')
        src = entry['path']
    else:
        src = f"gen/renoise-{entry}.mp4"
    if not Path(src).is_file(): sys.exit(f'{sid}: missing video {src}')
    wav = f'cut/{sid}.wav'
    lg = s.get('lang_code', lang)
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', src, '-ar', '16000', '-ac', '1', wav], check=True)
    from local_asr import transcribe
    transcribe(wav, f'cut/{sid}', lg)
    d = [t for t in json.loads(Path(f'cut/{sid}.json').read_text(encoding='utf-8-sig'))['transcription'] if t['text'].strip() and not t['text'].strip().startswith('[')]
    if not d: sys.exit(f'{sid}: no speech detected; preserve source and check the audio')
    heard = ''.join(t['text'] for t in d)
    st = min(t['offsets']['from'] for t in d) / 1000 if d else 0; en = max(t['offsets']['to'] for t in d) / 1000 if d else 0
    dur = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', src], capture_output=True, text=True).stdout)
    w, h = map(int, subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v', '-show_entries', 'stream=width,height', '-of', 'csv=p=0', src], capture_output=True, text=True).stdout.split(','))
    sz = size or f'{w - w % 2}x{h - h % 2}'          # 保持源尺寸（Grok 9:16 720p 是 720×1280，别拉成 720×1440）
    acc = difflib.SequenceMatcher(None, clean(s['t']), clean(heard)).ratio()
    if en <= 0 or en > dur + 0.25: sys.exit(f'{sid}: invalid ASR speech end {en}/{dur}')
    # Gesture demonstrations may need the silent return-to-rest after speech.
    keep = dur if s.get('keep_full') is True else min(dur, en + 0.25)
    keep = round(keep * 30) / 30
    keep = min(keep, int(dur * 30) / 30)
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', src, '-t', f'{keep:.3f}', '-vf', f'scale={sz.replace("x", ":")}:flags=lanczos,fps=30,format=yuv420p',
                    '-af', f'aresample=48000,afade=t=out:st={max(0, keep - 0.12):.3f}:d=0.12', '-ac', '2', '-c:v', 'libx264', '-crf', '17', '-preset', 'medium', '-c:a', 'aac', '-b:a', '192k', f'cut/{sid}.mp4'], check=True)
    rep.append(dict(id=sid, acc=round(acc, 3), speech=[round(st, 3), round(en, 3)], keep=keep, src_dur=dur, heard=heard, review='required' if acc < 0.85 else 'asr_pass_visual_review_pending'))
    print(f"{'⚠' if acc < 0.85 else ' '}{sid:5s} 准确率 {acc:.0%}  说话 {st:.2f}–{en:.2f}s  保留 {keep:.2f}/{dur:.2f}s  听到：{heard}")
Path('cut/qa.json').write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding='utf-8')
if any(r['acc'] < 0.85 for r in rep) and '--allow-low-asr' not in a:
    sys.exit('ASR mismatch: inspect cut/qa.json and sources; assembly paused. --allow-low-asr requires actual review.')
Path('cut/list.txt').write_text(''.join(f"file '{s['id']}.mp4'\n" for s in S), encoding='utf-8')
subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', 'cut/list.txt', '-c', 'copy', 'cut/joined.mp4'], check=True)
subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', 'cut/joined.mp4', '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', out_name], check=True)
print('拼接完成', out_name, round(sum(r['keep'] for r in rep), 2), '秒')
