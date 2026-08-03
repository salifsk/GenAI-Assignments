import os
import tempfile
from pathlib import Path
from typing import Optional

import boto3


def _normalize_prefix(prefix: Optional[str]) -> str:
    if not prefix:
        return ""
    prefix = prefix.strip()
    if prefix.startswith("s3://"):
        prefix = prefix[5:].split("/", 1)[1] if "/" in prefix[5:] else ""
    if prefix.startswith("/"):
        prefix = prefix[1:]
    return prefix


def resolve_document_paths(
    document_directory: Path,
    s3_bucket: Optional[str] = None,
    s3_prefix: Optional[str] = None,
    s3_client=None,
) -> list[Path]:
    """Resolve PDF documents from S3 when configured; otherwise fall back to local files."""
    bucket = s3_bucket or os.getenv("S3_BUCKET") or os.getenv("AWS_S3_BUCKET")
    s3_uri = os.getenv("S3_DOCUMENT_URI") or os.getenv("DOCUMENT_S3_URI")
    if s3_uri and s3_uri.startswith("s3://"):
        uri_without_scheme = s3_uri[5:]
        uri_parts = uri_without_scheme.split("/", 1)
        bucket = bucket or uri_parts[0]
        prefix = _normalize_prefix(
            s3_prefix or os.getenv("S3_PREFIX") or os.getenv("AWS_S3_PREFIX") or (uri_parts[1] if len(uri_parts) > 1 else "")
        )
    else:
        bucket = s3_bucket or os.getenv("S3_BUCKET") or os.getenv("AWS_S3_BUCKET")
        prefix = _normalize_prefix(s3_prefix or os.getenv("S3_PREFIX") or os.getenv("AWS_S3_PREFIX") or "")

    if bucket:
        region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
        client = s3_client or boto3.client("s3", region_name=region)
        response = client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        objects = response.get("Contents", [])
        pdf_keys = [item["Key"] for item in objects if str(item.get("Key", "")).lower().endswith(".pdf")]

        if pdf_keys:
            temp_dir = Path(tempfile.mkdtemp(prefix="s3-docs-"))
            downloaded_paths: list[Path] = []
            for key in pdf_keys:
                target_path = temp_dir / Path(key).name
                with target_path.open("wb") as handle:
                    client.download_fileobj(bucket, key, handle)
                downloaded_paths.append(target_path)
            return downloaded_paths

    if document_directory.exists():
        return sorted(document_directory.glob("*.pdf"))
    return []
