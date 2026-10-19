"""Small helpers that prevent stale Docker images from masquerading as current code."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FINGERPRINT_LABEL = "io.matsim-unified.source-fingerprint"


def source_fingerprint(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(item for item in path.rglob("*") if item.is_file())
        elif path.is_file():
            files.append(path)
    for path in sorted(set(files), key=lambda item: str(item)):
        try:
            relative = path.resolve().relative_to(PROJECT_ROOT.resolve())
        except ValueError:
            relative = Path(path.name)
        digest.update(str(relative).encode("utf-8"))
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest()


def image_matches_source(image_tag: str, fingerprint: str) -> bool:
    result = subprocess.run(
        [
            "docker", "image", "inspect",
            "--format", f"{{{{index .Config.Labels \"{FINGERPRINT_LABEL}\"}}}}",
            image_tag,
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == fingerprint


def fingerprint_build_args(fingerprint: str) -> list[str]:
    return ["--label", f"{FINGERPRINT_LABEL}={fingerprint}"]

