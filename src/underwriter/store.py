"""Deal document store.

Layout (same on local disk and in S3):

    <root>/<deal_id>/deal.json          loan request, portfolio, document index
    <root>/<deal_id>/<filename>         source documents (CSV)
    <root>/<deal_id>/work/<key>.json    parsed documents, overrides, metrics, evidence, memos
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol


class DealStore(Protocol):
    def read_text(self, deal_id: str, name: str) -> str: ...
    def write_text(self, deal_id: str, name: str, text: str) -> None: ...
    def exists(self, deal_id: str, name: str) -> bool: ...


class LocalDealStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _p(self, deal_id: str, name: str) -> Path:
        if ".." in deal_id or "/" in deal_id or ".." in name:
            raise ValueError("invalid deal or document id")
        return self.root / deal_id / name

    def read_text(self, deal_id: str, name: str) -> str:
        p = self._p(deal_id, name)
        if not p.exists():
            raise FileNotFoundError(f"{deal_id}/{name} not found")
        return p.read_text()

    def write_text(self, deal_id: str, name: str, text: str) -> None:
        p = self._p(deal_id, name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def exists(self, deal_id: str, name: str) -> bool:
        return self._p(deal_id, name).exists()


class S3DealStore:
    def __init__(self, bucket: str, prefix: str = "deals"):
        import boto3

        self.bucket, self.prefix = bucket, prefix.strip("/")
        self.s3 = boto3.client("s3")

    def _key(self, deal_id: str, name: str) -> str:
        if ".." in deal_id or "/" in deal_id or ".." in name:
            raise ValueError("invalid deal or document id")
        return f"{self.prefix}/{deal_id}/{name}"

    def read_text(self, deal_id: str, name: str) -> str:
        try:
            obj = self.s3.get_object(Bucket=self.bucket, Key=self._key(deal_id, name))
        except self.s3.exceptions.NoSuchKey as exc:
            raise FileNotFoundError(f"{deal_id}/{name} not found") from exc
        return obj["Body"].read().decode("utf-8")

    def write_text(self, deal_id: str, name: str, text: str) -> None:
        self.s3.put_object(
            Bucket=self.bucket,
            Key=self._key(deal_id, name),
            Body=text.encode("utf-8"),
            ServerSideEncryption="aws:kms",
        )

    def exists(self, deal_id: str, name: str) -> bool:
        try:
            self.s3.head_object(Bucket=self.bucket, Key=self._key(deal_id, name))
            return True
        except Exception:
            return False


def store_from_env() -> DealStore:
    bucket = os.environ.get("DEAL_BUCKET")
    if bucket:
        return S3DealStore(bucket, os.environ.get("DEAL_PREFIX", "deals"))
    default = Path(__file__).resolve().parents[2] / "evals" / "data" / "deals"
    return LocalDealStore(os.environ.get("DEAL_STORE_DIR", str(default)))


def read_json(store: DealStore, deal_id: str, name: str) -> Any:
    return json.loads(store.read_text(deal_id, name))


def write_json(store: DealStore, deal_id: str, name: str, obj: Any) -> None:
    store.write_text(deal_id, name, json.dumps(obj, indent=2, default=str))
