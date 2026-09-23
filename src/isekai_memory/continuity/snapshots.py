"""Bounded non-archive snapshots of explicitly allowed project files."""

import base64
import binascii
import hashlib
import re
from pathlib import PurePosixPath

from isekai_memory.continuity.common import canonical, digest, invalid

FORBIDDEN = {".git", ".isekai", ".ssh", ".aws", ".azure", ".kube", ".codex", ".claude", ".agents",
             "node_modules", ".venv", "credentials", "credentials.json", "id_rsa", "id_ed25519", ".netrc", ".npmrc"}


def safe_path(value):
    parts = value.split("/")
    if (not value or "\\" in value or ":" in value or PurePosixPath(value).is_absolute()
            or any(part in {"", ".", ".."} or part.lower() in FORBIDDEN or part.lower().startswith(".env")
                   or part.lower().endswith((".pem", ".key", ".p12", ".pfx")) for part in parts)
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise invalid("Unsafe or credential-bearing snapshot path")
    return value


def validate(snapshot, package, body):
    if snapshot is None:
        if package["workspace"]["state"] == "captured":
            raise invalid("Captured checkpoints require their snapshot bytes, not only a descriptor")
        return None
    if package["workspace"]["state"] != "captured":
        raise invalid("Snapshot bytes require captured workspace state")
    encoded = canonical(snapshot)
    if len(encoded) > body["checkpoint_max_bytes"]:
        raise invalid("Snapshot exceeds project checkpoint byte budget")
    seen = set()
    for file in snapshot["files"]:
        path = safe_path(file["path"])
        if path.casefold() in seen or not any(path == root or path.startswith(root + "/") for root in body["checkpoint_allowed_paths"]):
            raise invalid("Duplicate or non-allowlisted snapshot path")
        seen.add(path.casefold())
        # Null means an explicit deletion relative to the pinned commit.
        if file["content_base64"] is None:
            if package["schema_version"] == 2:
                raise invalid("Directory snapshots cannot contain Git-relative deletions")
            if file["digest"] is not None or file.get("executable", False):
                raise invalid("Deleted files have no content digest")
            continue
        try:
            raw = base64.b64decode(file["content_base64"], validate=True)
        except (ValueError, binascii.Error) as exc:
            raise invalid("Invalid snapshot base64") from exc
        if base64.b64encode(raw).decode() != file["content_base64"]:
            raise invalid("Snapshot base64 must be canonical")
        if file["digest"] != "sha256:" + hashlib.sha256(raw).hexdigest():
            raise invalid("Snapshot file digest mismatch")
        if re.search(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:AKIA|ASIA)[A-Z0-9]{16}|gh[pousr]_[A-Za-z0-9]{30,}", raw):
            raise invalid("Recognizable credential material is not allowed in checkpoints")
    # Reject parent/child collisions even on case-insensitive receiving filesystems.
    if any("/".join(path.split("/")[:index]) in seen for path in seen for index in range(1, len(path.split("/")))):
        raise invalid("Snapshot contains a file/directory path collision")
    snapshot_digest = digest(snapshot)
    artifact = next(item for item in package["artifacts"] if item["id"] == package["workspace"]["snapshot_artifact_id"])
    if (artifact["digest"] != snapshot_digest or artifact["size_bytes"] != len(encoded)
            or artifact["source_id"] != "memory-checkpoint" or artifact["reference"] != "snapshot-" + snapshot_digest[7:]):
        raise invalid("Snapshot descriptor must bind the stored Memory checkpoint bytes")
    return snapshot_digest
