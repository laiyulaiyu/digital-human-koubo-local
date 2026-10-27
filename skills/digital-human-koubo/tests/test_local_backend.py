"""Contract tests for the new backend boundary; real GPU/ASR checks are separate."""
import importlib.util
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import local_backend as backend


class BackendContracts(unittest.TestCase):
    def setUp(self):
        # Keep temporary writes inside the caller's authorized project workspace.
        self.temp = tempfile.TemporaryDirectory(prefix='koubo-test-', dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'config.json'
        backend.write(self.config, {'workspace': str(self.root), 'runner': 'unused'})
        (self.root / 'frame.png').write_bytes(b'contract fixture; never submitted')
        self.script = self.root / 'script.json'
        self.manifest = self.root / 'tasks.json'
        self.row = dict(id='s1', t='先核对来源。', seconds=6, first='frame.png', width=448, height=800)

    def build(self, row=None):
        backend.write(self.script, [row or self.row])
        runner = types.SimpleNamespace(frame_count=lambda seconds: 158)
        with patch.object(backend, 'load_runner', return_value=runner):
            return backend.build_manifest(self.script, self.manifest, self.config)

    def test_relative_frame_and_exact_dialogue(self):
        result = self.build()['segments'][0]
        self.assertEqual(result['first'], str(self.root / 'frame.png'))
        self.assertIn('<d>[Mandarin Chinese] 先核对来源。</d>', result['prompt'])
        self.assertEqual(result['effective_seconds'], 158 / 24)
        self.assertFalse(result['turbo'])

    def test_invalid_duration_and_canvas_rejected(self):
        for changes in ({'seconds': 0}, {'seconds': 16}, {'seconds': float('nan')}, {'width': 447}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.build(self.row | changes)

    def test_cloud_and_traversal_inputs_rejected(self):
        for changes in ({'first': 'https://example.com/a.png'}, {'id': '../s1'}, {'first': 'missing.png'}):
            with self.subTest(changes=changes), self.assertRaises((ValueError, FileNotFoundError)):
                self.build(self.row | changes)
        with self.assertRaises(ValueError):
            backend.inside(self.root.parent / 'escape.mp4', self.root)

    def test_reference_mode_must_be_explicit_and_unambiguous(self):
        for changes in ({'refs': ['frame.png']}, {'first': None, 'refs': ['frame.png']}, {'mode': 'reference'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.build(self.row | changes)
        result = self.build(self.row | {'first': None, 'refs': ['frame.png'], 'prompt': 'Explicit Ref2VA prompt'})
        self.assertEqual(result['segments'][0]['mode'], 'reference')

    def test_mapping_survives_failed_execution(self):
        self.build()
        job = self.root / 'job.json'
        record = {'id': 'known-task', 'state': 'prepared'}
        backend.write(job, record)
        def fail(job_path, record, config):
            # Submission must already have been journaled before contacting ComfyUI.
            self.assertEqual(backend.read(self.root / 'ids.json')['s1']['job_id'], 'known-task')
            backend.write(job_path, record | {'state': 'submission_unknown'})
            raise RuntimeError('response lost')
        runner = types.SimpleNamespace(prepare=lambda args, cfg: (job, record), execute=fail, read=backend.read)
        with patch.object(backend, 'load_runner', return_value=runner), self.assertRaises(RuntimeError):
            backend.run_manifest(self.manifest)
        self.assertEqual(backend.read(self.root / 'ids.json')['s1']['state'], 'submission_unknown')

    def test_dry_run_never_executes(self):
        self.build()
        record = {'id': 'prepared-only', 'state': 'prepared'}
        runner = types.SimpleNamespace(prepare=lambda args, cfg: (self.root / 'job.json', record))
        with patch.object(backend, 'load_runner', return_value=runner):
            mapping = backend.run_manifest(self.manifest, dry_run=True)
        self.assertEqual(mapping['s1']['state'], 'prepared')

    def test_explicit_cloud_branch_still_emits_original_task_array(self):
        backend.write(self.script, [self.row])
        subprocess.run([sys.executable, '-X', 'utf8', str(SCRIPTS / 'build_tasks.py'), str(self.script),
                        str(self.manifest), '--backend', 'renoise'], cwd=self.root, check=True, capture_output=True)
        result = backend.read(self.manifest)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['kind'], 'video')
        self.assertIn('idempotencyKey', result[0])


class MotionContracts(unittest.TestCase):
    def test_lora_chain_updates_both_consumers_without_changing_source(self):
        from local_lora import add_to_graph
        original = {'6': {'class_type': 'LoraLoaderModelOnly', 'inputs': {}},
                    '7': {'class_type': 'BasicGuider', 'inputs': {'model': ['6', 0]}},
                    '10': {'class_type': 'BasicScheduler', 'inputs': {'model': ['6', 0]}}}
        graph = add_to_graph(original, [{'name': 'motion.safetensors', 'strength': 0.5}])
        self.assertEqual(graph['9000']['inputs']['model'], ['6', 0])
        self.assertEqual(graph['7']['inputs']['model'], ['9000', 0])
        self.assertEqual(graph['10']['inputs']['model'], ['9000', 0])
        self.assertEqual(original['7']['inputs']['model'], ['6', 0])

    def test_lora_hash_change_and_escape_are_rejected(self):
        from local_lora import describe_loras
        with tempfile.TemporaryDirectory(prefix='koubo-lora-', dir=Path.cwd()) as directory:
            root = Path(directory); models = root / 'models/loras'; models.mkdir(parents=True)
            file = models / 'motion.safetensors'; file.write_bytes(b'contract fixture')
            config = {'comfy_root': str(root)}
            rows = describe_loras([{'name': file.name, 'strength': 0.5}], config)
            self.assertEqual(rows[0]['strength'], 0.5)
            file.write_bytes(b'changed')
            with self.assertRaises(ValueError): describe_loras(rows, config)
            with self.assertRaises(ValueError): describe_loras([{'name': '../escape.safetensors'}], config)

    def test_gestures_follow_dialogue_order_and_preserve_text(self):
        row = {'t': '先看来源，再看证据。', 'gestures': [
            {'on': '先看来源', 'action': 'opens her right palm'},
            {'on': '再看证据', 'action': 'raises her left palm'}]}
        prompt = backend.prompt_for(row, 6.5, 'explaining')
        self.assertIn('<d>[Mandarin Chinese] 先看来源，再看证据。</d>', prompt)
        self.assertIn('complete hands visible', prompt)
        row['gestures'].reverse()
        with self.assertRaises(ValueError): backend.prompt_for(row, 6.5, 'explaining')


class VoiceCompatibility(unittest.TestCase):
    def test_fft_preserves_original_linear_convolution(self):
        import numpy as np
        spec = importlib.util.spec_from_file_location('voice_unify', SCRIPTS / 'voicefx/unify.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        dry = np.random.default_rng(42).normal(size=513).astype(np.float32)
        for wet in (0, 0.08, 0.24):
            original = np.stack([np.convolve(dry, module.IR[:, c], mode='full')[:len(dry)] for c in range(2)], 1)
            original = np.stack([dry, dry], 1) * (1 - wet) + original * wet
            np.testing.assert_allclose(module.roomify(dry, wet), original, rtol=2e-6, atol=2e-6)


class OriginalAlignmentCompatibility(unittest.TestCase):
    def test_interpolation_stays_in_cut_and_second_segment_is_absolute(self):
        with tempfile.TemporaryDirectory(prefix='koubo-align-', dir=Path.cwd()) as directory:
            root = Path(directory)
            (root / 'cut').mkdir()
            backend.write(root / 'script.json', [{'id': 's1', 't': '核对来源。'}, {'id': 's2', 't': '再看时间。'}])
            backend.write(root / 'cut/qa.json', [{'id': 's1', 'keep': 0.9}, {'id': 's2', 'keep': 1.1}])
            # Simulates sparse recognition near a cut boundary. Missing characters
            # must not extrapolate subtitles past the end of their own segment.
            backend.write(root / 'cut/s1.json', {'transcription': [{'text': '核', 'offsets': {'from': 800, 'to': 900}}]})
            backend.write(root / 'cut/s2.json', {'transcription': [{'text': '再看时间', 'offsets': {'from': 100, 'to': 900}}]})
            subprocess.run([sys.executable, '-X', 'utf8', str(SCRIPTS / 'align.py'), 'script.json', '--out', 'tl.json'],
                           cwd=root, check=True, capture_output=True)
            timeline = backend.read(root / 'tl.json')
            self.assertEqual(timeline['total'], 2.0)
            self.assertEqual(timeline['segs'][1]['start'], 0.9)
            for segment in timeline['segs']:
                stamps = list(segment['chars'].values())
                self.assertEqual(stamps, sorted(stamps))
                self.assertGreaterEqual(min(stamps), segment['start'])
                self.assertLess(max(stamps), segment['end'])


if __name__ == '__main__':
    unittest.main()
