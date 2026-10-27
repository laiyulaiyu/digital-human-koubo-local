"""Add native model-only LoRA nodes to the existing H3 graph; no new runner."""
import copy
import hashlib
import math
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def describe_loras(rows, config):
    root = (Path(config['comfy_root']) / 'models/loras').resolve()
    result = []
    for row in rows:
        name = str(row['name']).replace('\\', '/')
        file = (root / name).resolve()
        if not file.is_relative_to(root) or Path(name).is_absolute() or file.suffix != '.safetensors':
            raise ValueError('LoRA must be a .safetensors file inside models/loras')
        strength = float(row.get('strength', 0.5))
        if not math.isfinite(strength) or not 0 < strength <= 1:
            raise ValueError('LoRA strength must be > 0 and <= 1')
        if not file.is_file():
            raise FileNotFoundError(file)
        sha = digest(file)
        if row.get('sha256') and row['sha256'] != sha:
            raise ValueError('LoRA changed since manifest creation; inspect and rebuild: ' + name)
        result.append(dict(name=name, strength=strength, sha256=sha, bytes=file.stat().st_size))
    return result


def add_to_graph(graph, loras):
    graph = copy.deepcopy(graph)
    consumers = [node['inputs'] for node in graph.values()
                 if node['class_type'] in ('BasicGuider', 'BasicScheduler')]
    if not consumers or any(node['model'] != consumers[0]['model'] for node in consumers):
        raise ValueError('Unexpected H3 model wiring; refusing to patch an unknown graph')
    previous = consumers[0]['model']
    for index, lora in enumerate(loras):
        key = str(9000 + index)
        if key in graph:
            raise ValueError('LoRA node id collision')
        graph[key] = dict(class_type='LoraLoaderModelOnly', inputs=dict(
            model=previous, lora_name=lora['name'], strength_model=lora['strength']))
        previous = [key, 0]
    for node in consumers:
        node['model'] = previous
    return graph
