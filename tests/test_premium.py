"""Checks for editable motion and non-destructive pack generation."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from premium_pack import ANIMS, SFX, build, render_text, state, SOURCE


class PremiumTests(unittest.TestCase):
    def test_motion_has_alpha_and_changes_over_time(self):
        for index, name in enumerate(ANIMS):
            with self.subTest(animation=name):
                early = np.array(render_text('TẤN PHÁT • CÔNG NGHỆ', 'Technology', index, .08))
                middle = np.array(render_text('TẤN PHÁT • CÔNG NGHỆ', 'Technology', index, .55))
                self.assertEqual(early.shape, (540, 960, 4))
                self.assertEqual(middle[:, :, 3].min(), 0)
                self.assertGreater(middle[:, :, 3].max(), 0)
                self.assertFalse(np.array_equal(early, middle))
                self.assertEqual(state(index, 1)['opacity'], 0)

    def test_preserves_existing_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / 'existing'
            directory.mkdir()
            sentinel = directory / 'user.txt'
            sentinel.write_text('keep this')
            with self.assertRaises(FileExistsError):
                build(directory)
            self.assertEqual(sentinel.read_text(), 'keep this')

    def test_brief_cues_and_catalog(self):
        cues = json.loads((SOURCE / 'premium_cues.json').read_text())
        self.assertEqual(len(SFX), 40)
        self.assertEqual(len({name for name, _ in SFX}), 40)
        self.assertEqual(len(cues), 74)
        self.assertEqual(sum(c['audio_only'] for c in cues), 1)
        self.assertEqual(cues[0]['start'], 3.875)
        self.assertEqual(cues[-1]['start'], 313)


if __name__ == '__main__':
    unittest.main()
