"""Local CPU ASR -> the whisper.cpp JSON schema consumed by assemble/align.

Use installed models only. The expected script is deliberately not an ASR prompt.
DH_ASR_MODEL may be a faster-whisper directory, .pt model, or whisper.cpp .bin.
"""
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

_models = {}


def find_model():
    specified = os.environ.get('DH_ASR_MODEL') or os.environ.get('WHISPER_MODEL')
    if specified:
        path = Path(specified).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError('ASR model does not exist: ' + str(path))
        return path
    cache = Path.home() / '.cache'
    if importlib.util.find_spec('faster_whisper'):
        for name in ('large-v3', 'medium', 'small', 'base'):
            matches = list((cache / f'huggingface/hub/models--Systran--faster-whisper-{name}/snapshots').glob('*/model.bin'))
            if matches:
                return matches[0].parent
    # Preserve the original whisper.cpp model discovery on existing installations.
    if shutil.which('whisper-cli'):
        for relative in ('Library/Application Support/Murmur/models/ggml-medium-q5_0.bin',
                         'models/ggml-medium-q5_0.bin', '.cache/whisper/ggml-medium-q5_0.bin',
                         'models/ggml-medium.bin'):
            path = Path.home() / relative
            if path.is_file():
                return path
    if importlib.util.find_spec('whisper'):
        for name in ('medium', 'small', 'base'):
            path = cache / 'whisper' / (name + '.pt')
            if path.exists():
                return path
    raise FileNotFoundError('No cached local ASR model; configure DH_ASR_MODEL')


def transcribe(wav, prefix, language='zh'):
    path = find_model()
    if path.suffix == '.bin':
        executable = shutil.which('whisper-cli')
        if not executable:
            raise FileNotFoundError('whisper-cli is needed for a .bin ASR model')
        cmd = [executable, '-m', str(path), '-l', language, '-oj', '-of', str(prefix), '-f', str(wav)]
        if language == 'zh':
            cmd += ['--prompt', '以下是普通话的句子。', '-ml', '1']
        subprocess.run(cmd, check=True, capture_output=True)
        return
    key = str(path)
    if path.is_dir():
        from faster_whisper import WhisperModel
        if key not in _models:
            _models[key] = WhisperModel(key, device='cpu', compute_type='int8', cpu_threads=6, local_files_only=True)
        segments, info = _models[key].transcribe(str(wav), language=language, beam_size=5,
                                                condition_on_previous_text=False, word_timestamps=True,
                                                vad_filter=False, temperature=0)
        backend = 'faster-whisper-cpu-int8'
    else:
        import torch
        import whisper
        torch.set_num_threads(6)
        if key not in _models:
            _models[key] = whisper.load_model(key, device='cpu')
        result = _models[key].transcribe(str(wav), language=language, fp16=False, temperature=0,
                                         condition_on_previous_text=False, word_timestamps=True)
        segments = result['segments']
        backend = 'openai-whisper-cpu'
    rows = []
    for seg in segments:
        words = seg.get('words', []) if isinstance(seg, dict) else seg.words
        if not words:
            words = [seg]
        for word in words:
            if isinstance(word, dict):
                text = word.get('word', word.get('text', ''))
                start, end = word['start'], word['end']
            else:
                text = getattr(word, 'word', getattr(word, 'text', ''))
                start, end = word.start, word.end
            if text.strip():
                rows.append(dict(text=text, offsets={'from': round(start * 1000), 'to': round(end * 1000)}))
    Path(str(prefix) + '.json').write_text(json.dumps(dict(transcription=rows, backend=backend, model=key),
                                                        ensure_ascii=False, indent=2), encoding='utf-8')
