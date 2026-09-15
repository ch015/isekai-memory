"""Verify an exported Skill using unchanged Core archive/schema/digest checks.

Reads the bounded export result on stdin. Only materializes a temporary directory;
never installs a Skill or changes a Project, Lock, credentials or Core code.
"""

import base64
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.environ["MEMORY_CORE_SOURCE"])

from isekai.artifacts.archive import ArtifactArchive  # noqa: E402
from isekai.artifacts.verification import ArtifactVerifier  # noqa: E402
from isekai.infrastructure.errors import IsekaiError  # noqa: E402


def main():
    exported = json.loads(sys.stdin.read(1024 * 1024))
    payload = base64.b64decode(exported["archive_base64"], validate=True)
    assert "sha256:" + hashlib.sha256(payload).hexdigest() == exported["archive_digest"]
    with tempfile.TemporaryDirectory(prefix="isekai-memory-skill-verifier-") as directory:
        root = Path(directory)
        archive = root / "skill.tar.gz"
        archive.write_bytes(payload)
        tree = root / "tree"
        tree.mkdir()
        ArtifactArchive().extract(archive, tree)
        verified = ArtifactVerifier().verify(tree)
        assert verified.manifest["kind"] == "skill"
        assert verified.artifact_digest == exported["artifact_digest"] and verified.manifest_digest == exported["manifest_digest"]
        assert not verified.verified_signers
        (tree / "instructions.md").write_text("tampered instructions")
        try:
            ArtifactVerifier().verify(tree)
        except IsekaiError:
            pass
        else:
            raise AssertionError("Core accepted tampered Skill content")
    print(json.dumps({"core_native_skill_verifier": True, "digest_tamper_rejected": True, "installed": False}))


if __name__ == "__main__":
    main()
