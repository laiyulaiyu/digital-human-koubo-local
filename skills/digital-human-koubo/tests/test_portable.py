"""Relocation and bundled-workflow tests: no GPU, network, or external skill."""
from pathlib import Path
import sys
import tempfile
import unittest
import subprocess

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import local_backend as backend
import local_config


class PortablePackage(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='koubo-portable-', dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.comfy = self.root / 'existing-comfy'; self.comfy.mkdir()
        (self.comfy / 'main.py').write_text('# fixture, never executed', encoding='utf-8')
        self.config = self.root / 'settings/local.json'
        subprocess.run([sys.executable, '-X', 'utf8', str(SCRIPTS / 'configure.py'), '--comfy-root', str(self.comfy),
                        '--python', sys.executable, '--workspace', str(self.root / 'work'), '--out', str(self.config)],
                       check=True, capture_output=True)

    def test_configure_bundles_runner_and_workflows(self):
        config = local_config.load(self.config)
        self.assertEqual(Path(config['runner']), SCRIPTS / 'local_media.py')
        self.assertEqual(len(list((Path(config['templates']) / 'api').glob('*.api.json'))), 6)
        self.assertTrue(Path(config['workspace']).is_dir())

    def test_native_graph_preparation_without_external_skill(self):
        from PIL import Image
        root = self.root / 'work/demo'; root.mkdir(parents=True)
        Image.new('RGB', (64, 64), '#888888').save(root / 'first.png')
        backend.write(root / 'script.json', [{'id': 's1', 't': '先看来源。', 'seconds': 4, 'first': 'first.png', 'seed': 1}])
        backend.build_manifest(root / 'script.json', root / 'tasks.json', self.config)
        mapping = backend.run_manifest(root / 'tasks.json', dry_run=True)
        record = backend.read(mapping['s1']['job'])
        graph = backend.read(Path(mapping['s1']['job']).parent / record['graph'])
        self.assertEqual(record['state'], 'prepared')
        self.assertEqual(graph['13']['class_type'], 'VAEDecodeAudio')
        self.assertEqual(graph['5']['inputs']['prompt'], backend.read(root / 'tasks.json')['segments'][0]['prompt'])

    def test_existing_absolute_paths_keep_their_spelling(self):
        raw = backend.read(self.config)
        config = local_config.load(self.config)
        self.assertEqual(config['comfy_root'], raw['comfy_root'])
        self.assertEqual(config['python'], raw['python'])


if __name__ == '__main__': unittest.main()
