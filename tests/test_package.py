from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import package


class PackageTest(unittest.TestCase):
    def test_release_inputs_exclude_generated_and_private_files(self):
        paths = list(package.source_files())
        self.assertTrue(paths)
        for path in paths:
            parts = path.relative_to(ROOT).parts
            self.assertNotIn('build', parts)
            self.assertNotIn('dist', parts)
            self.assertNotIn('__pycache__', parts)
            self.assertFalse(path.name.endswith('.local.json'))
        package.privacy_check(paths)

    def test_privacy_scanner_rejects_common_identifiers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'example.txt'
            samples = ['/' + 'Users/' + 'example/' + 'file', '.'.join(['192', '0', '2', '1']), ':'.join(['AA'] * 6)]
            for sample in samples:
                path.write_text(sample)
                with patch('package.ROOT', root), self.assertRaises(ValueError):
                    package.privacy_check([path])


if __name__ == '__main__':
    unittest.main()
