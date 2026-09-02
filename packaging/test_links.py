"""Check restore failure cases without touching the real dependency tree."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('restore_links', Path(__file__).resolve().parents[1] / 'launcher/restore_links.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RestoreTests(unittest.TestCase):
    def test_reject_escaping_path(self):
        for value in ('../outside', 'dsh-core/../../outside', 'C:/outside', '/dsh-core/x', 'dsh-core\\x'):
            with self.assertRaises(ValueError):
                module.contained(Path.cwd(), value)

    def test_cycle_collision_and_missing_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / 'launcher').mkdir()
            for name in ('a', 'b'):
                (root / 'dsh-core' / name).mkdir(parents=True)
            manifest = root / 'launcher/bundle-links.json'
            entries = [{'path': 'dsh-core/a/peer', 'target': 'dsh-core/b'},
                       {'path': 'dsh-core/b/peer', 'target': 'dsh-core/a'}]
            manifest.write_text(json.dumps({'version': 1, 'links': entries}), encoding='utf-8')
            try:
                self.assertEqual(module.restore(root), 2)
                self.assertEqual(module.restore(root), 0)
                os.rmdir(root / 'dsh-core/a/peer')
                (root / 'dsh-core/a/peer').mkdir()
                with self.assertRaisesRegex(RuntimeError, 'ordinary path'):
                    module.restore(root)
                (root / 'dsh-core/a/peer').rmdir()
                entries[0]['target'] = 'dsh-core/missing'
                manifest.write_text(json.dumps({'version': 1, 'links': entries}), encoding='utf-8')
                with self.assertRaisesRegex(RuntimeError, 'Missing bundled'):
                    module.restore(root)
            finally:
                for name in ('a', 'b'):
                    link = root / 'dsh-core' / name / 'peer'
                    if os.path.lexists(link):
                        os.rmdir(link)


if __name__ == '__main__':
    unittest.main()
