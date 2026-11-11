"""Second copy of the raw archive on another drive."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from .archive import MANIFEST, iso, utcnow

STATE = "mirror_state.json"
SKIP = {MANIFEST, STATE}


def _archive_files(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name not in SKIP and not p.name.endswith(".tmp"):
            yield p


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    shutil.copyfile(src, tmp)
    with open(tmp, "rb") as fh:
        os.fsync(fh.fileno())
    os.replace(tmp, dst)


def missing_files(archive_root: Path, mirror_root: Path) -> list[str]:
    out = []
    for src in _archive_files(archive_root):
        dst = mirror_root / src.relative_to(archive_root)
        # raw files are written once; the day's feature log may be replaced later that day (newer mtime)
        if not dst.exists() or dst.stat().st_size != src.stat().st_size or dst.stat().st_mtime < src.stat().st_mtime:
            out.append(str(src.relative_to(archive_root)))
    return out


def mirror(archive_root: Path, mirror_root: Path, mount: Path | None) -> dict:
    """Copy every file missing in the mirror, then the manifest. Records the result in mirror_state.json."""
    archive_root, mirror_root = Path(archive_root), Path(mirror_root)
    state_path = archive_root / STATE
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    state["last_attempt"] = iso(utcnow())
    try:
        if mount is not None and not os.path.ismount(mount):
            raise OSError(f"Laufwerk {mount} ist nicht eingehängt")
        todo = missing_files(archive_root, mirror_root)
        for rel in todo:
            _copy(archive_root / rel, mirror_root / rel)
        if (archive_root / MANIFEST).exists():
            _copy(archive_root / MANIFEST, mirror_root / MANIFEST)
        result = {"ok": True, "copied": len(todo)}
        state.update(last_ok=state["last_attempt"], last_error=None)
    except OSError as exc:
        result = {"ok": False, "error": str(exc)}
        state["last_error"] = f"{state['last_attempt']}: {exc}"
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    return result


def verify(archive_root: Path, mirror_root: Path) -> list[str]:
    """Return relative paths whose mirror copy is missing or differs (SHA-256 of the stored bytes)."""
    bad = []
    for src in _archive_files(Path(archive_root)):
        rel = src.relative_to(archive_root)
        dst = Path(mirror_root) / rel
        if not dst.exists() or hashlib.sha256(src.read_bytes()).digest() != hashlib.sha256(dst.read_bytes()).digest():
            bad.append(str(rel))
    return bad
