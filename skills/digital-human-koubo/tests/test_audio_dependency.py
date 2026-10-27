"""Catch the PyAV metadata_errors API regression without downloading ASR models."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import wave


class AudioDependency(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('faster_whisper'), 'optional ASR dependency not installed')
    def test_faster_whisper_can_decode_local_wav(self):
        from faster_whisper.audio import decode_audio
        with tempfile.TemporaryDirectory(prefix='koubo-audio-', dir=Path.cwd()) as directory:
            path = Path(directory) / 'silence.wav'
            with wave.open(str(path), 'wb') as out:
                out.setnchannels(1); out.setsampwidth(2); out.setframerate(16000)
                out.writeframes(b'\0\0' * 1600)
            samples = decode_audio(str(path))
            self.assertEqual(len(samples), 1600)


if __name__ == '__main__': unittest.main()
