import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from document_sources import resolve_document_paths


class FakeS3Client:
    def list_objects_v2(self, Bucket, Prefix):
        return {
            "Contents": [
                {"Key": "docs/a.pdf"},
                {"Key": "docs/sub/b.pdf"},
            ]
        }

    def download_fileobj(self, Bucket, Key, fileobj):
        fileobj.write(b"%PDF-1.4\n")


class DocumentSourcesTests(unittest.TestCase):
    def test_resolve_document_paths_uses_s3_when_configured(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch("document_sources.boto3.client", return_value=FakeS3Client()):
                paths = resolve_document_paths(
                    Path(tmp_dir),
                    s3_bucket="my-bucket",
                    s3_prefix="docs/",
                )

            self.assertEqual(len(paths), 2)
            self.assertTrue(all(path.exists() for path in paths))
            self.assertTrue(any(path.name == "a.pdf" for path in paths))
            self.assertTrue(any(path.name == "b.pdf" for path in paths))


if __name__ == "__main__":
    unittest.main()
