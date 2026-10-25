"""
Where the pipeline's files live, and keeping them in step with S3.

Every file the pipeline makes - pipeline.db, the markdown versions, the PDFs -
lives under one data folder, and is referred to by its path relative to that
folder, e.g. "source-extracted-files/versions/abs-....md". The same relative
path is used as the file's key in S3, so the database never needs to know
which of the two it is running against.

    PIPELINE_DATA_DIR   the data folder (default: <repo>/data; on Lambda: /tmp/data)
    PIPELINE_S3_BUCKET  when set, files are also downloaded from / uploaded to
                        this bucket. When not set (running locally), every
                        function here is a no-op and only the local folder is used.

Settings files (sources.json, collect_settings.json) are read from
config/<name> in the bucket when it is there, so they can be changed on AWS
without redeploying, and from pipeline/<name> in the code otherwise.
"""

import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("PIPELINE_DATA_DIR") or REPO_ROOT / "data")
BUCKET = os.environ.get("PIPELINE_S3_BUCKET") or None

_s3 = None


def _client():
    global _s3
    if _s3 is None:
        import boto3  # built into Lambda; only needed locally when testing with S3
        _s3 = boto3.client("s3")
    return _s3


def _missing(exc) -> bool:
    code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
    return code in ("404", "NoSuchKey", "NotFound")


def local(rel_path: str) -> Path:
    """The local path of a file, from its data-folder-relative path."""
    return DATA_DIR / rel_path


def relative(path: Path) -> str:
    """The data-folder-relative path of a local file (also its S3 key)."""
    return Path(path).resolve().relative_to(DATA_DIR.resolve()).as_posix()


def download(rel_path: str) -> bool:
    """Fetch a file from S3 into the data folder, replacing any local copy.
    Returns False if S3 does not have it. Without a bucket, just reports
    whether the local file exists."""
    target = local(rel_path)
    if not BUCKET:
        return target.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        _client().download_file(BUCKET, rel_path, str(target))
        return True
    except Exception as exc:
        if _missing(exc):
            return False
        raise


def upload(rel_path: str) -> None:
    """Copy a file from the data folder to S3. Does nothing without a bucket."""
    if BUCKET:
        _client().upload_file(str(local(rel_path)), BUCKET, rel_path)


def exists(rel_path: str) -> bool:
    """Is the file here (or in S3, when a bucket is set)?"""
    if local(rel_path).exists():
        return True
    if not BUCKET:
        return False
    try:
        _client().head_object(Bucket=BUCKET, Key=rel_path)
        return True
    except Exception as exc:
        if _missing(exc):
            return False
        raise


def read_config(name: str):
    """A JSON settings file: config/<name> from S3 when a bucket is set and the
    file is there, otherwise the copy shipped in pipeline/<name>."""
    if BUCKET and download(f"config/{name}"):
        return json.loads(local(f"config/{name}").read_text(encoding="utf-8"))
    return json.loads((Path(__file__).resolve().parent / name).read_text(encoding="utf-8"))
