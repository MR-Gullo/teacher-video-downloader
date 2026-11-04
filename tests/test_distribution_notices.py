"""Verify bundled notices are complete and bound to the reviewed hashes."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_payload', ROOT / 'scripts/macos/prepare_payload.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class DenoNoticeTests(unittest.TestCase):
    def test_reviewed_inventory_copies_and_detects_tampering(self):
        source = ROOT / 'scripts/macos/licenses/deno-third-party'
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / 'notices'
            digest = prepare.copy_deno_notices(source, destination)
            self.assertEqual(digest, prepare.sha(source / 'PROVENANCE.json'))
            self.assertTrue((destination / 'MPL-SOURCES.zip').is_file())
            (destination / 'THIRD-PARTY-NOTICES.txt').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                prepare.copy_deno_notices(destination, Path(temporary) / 'invalid')

    def test_missing_review_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            (source / 'PROVENANCE.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                prepare.copy_deno_notices(source, source / 'invalid')


if __name__ == '__main__':
    unittest.main()
