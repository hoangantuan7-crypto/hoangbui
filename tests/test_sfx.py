import tempfile
import unittest
from pathlib import Path
import sys

import numpy as np
from scipy.io import wavfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from generate_sfx import export, RATE


class SfxTest(unittest.TestCase):
    def test_exports_and_preserves_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = export(Path(directory))
            self.assertEqual(len(paths), 5)
            for path in paths:
                rate, audio = wavfile.read(path)
                self.assertEqual(rate, RATE)
                self.assertEqual(audio.dtype, np.int16)
                self.assertEqual(audio.ndim, 1)
                self.assertGreater(len(audio), RATE // 4)
                self.assertGreater(np.sqrt(np.mean(audio.astype(float)**2)), 100)
                self.assertLess(np.max(np.abs(audio.astype(float))), 32767)
                self.assertEqual((audio[0], audio[-1]), (0, 0))
            before = paths[0].read_bytes()
            with self.assertRaises(FileExistsError):
                export(Path(directory))
            self.assertEqual(paths[0].read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
