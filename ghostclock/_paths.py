"""Repo-relative locations, overridable with environment variables (no hard-coded user paths).

GHOSTCLOCK_DATA    root for local data (default: <repo>/data)
GHOSTCLOCK_GB_DIR  GB reference parquet files (default: $GHOSTCLOCK_DATA/gb)
GHOSTCLOCK_OUT     outputs of the CLI tools (default: <repo>/out)
GHOSTCLOCK_FFMPEG_DIR  folder holding ffmpeg/ffprobe if they are not on PATH
"""
from __future__ import annotations

import glob
import os
import shutil
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
REPO_ROOT = PKG_DIR.parent
PKG_DATA = PKG_DIR / "data"
DATA_DIR = Path(os.environ.get("GHOSTCLOCK_DATA", REPO_ROOT / "data"))
GB_DIR = Path(os.environ.get("GHOSTCLOCK_GB_DIR", DATA_DIR / "gb"))
OUT_DIR = Path(os.environ.get("GHOSTCLOCK_OUT", REPO_ROOT / "out"))


def rel(p) -> str:
    """Path relative to the repo when possible (for provenance strings), else absolute."""
    p = Path(p)
    try:
        return p.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(p)


def find_tool(name: str):
    """Locate ffmpeg/ffprobe: PATH, then $GHOSTCLOCK_FFMPEG_DIR, then a WinGet install."""
    p = shutil.which(name)
    if p:
        return p
    d = os.environ.get("GHOSTCLOCK_FFMPEG_DIR")
    if d:
        for cand in (Path(d) / name, Path(d) / f"{name}.exe"):
            if cand.exists():
                return str(cand)
    hits = glob.glob(os.path.expandvars(
        rf"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\*\bin\{name}.exe"))
    return hits[0] if hits else None
