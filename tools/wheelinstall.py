"""Minimal wheel installer.

Why this exists: on this machine `pip install` cannot finish, because the
parent directory carries an `Everyone Deny DeleteSubdirectoriesAndFiles` ACE
and pip has to rename/delete its own temp files. This script resolves
dependencies itself and unpacks wheels with zipfile, which only creates files.

Usage:
    py -3 wheelinstall.py --target <site-packages> flet==1.0.4
    py -3 wheelinstall.py --target <site-packages> --list flet

Only Windows + CPython is targeted, which is all this project needs.
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import zipfile
from pathlib import Path

import requests
from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import InvalidVersion, Version

MIRRORS = [
    "http://mirrors.aliyun.com/pypi/simple",
    "http://pypi.tuna.tsinghua.edu.cn/simple",
]

PY = f"cp{sys.version_info.major}{sys.version_info.minor}"
PLATFORM = "win_amd64"


class Resolver:
    def __init__(self, offline_prefixes: tuple[str, ...] = ()):
        self._index_cache: dict[str, str] = {}
        self._picked: dict[str, tuple[Version, str, str]] = {}  # name -> (ver, url, filename)
        self.seen: set[str] = set()
        self.offline_prefixes = offline_prefixes

    # ---------------------------------------------------------------- index --
    def index(self, name: str) -> str:
        key = canonicalize_name(name)
        if key in self._index_cache:
            return self._index_cache[key]
        last = None
        for mirror in MIRRORS:
            try:
                resp = requests.get(f"{mirror}/{key}/", timeout=45)
                if resp.status_code == 200:
                    self._index_cache[key] = resp.text
                    return resp.text
            except Exception as exc:  # noqa: BLE001
                last = exc
        raise RuntimeError(f"cannot fetch index for {name}: {last}")

    # -------------------------------------------------------------- choose ---
    @staticmethod
    def _score(platform_tag: str, abi_tag: str, py_tag: str) -> int | None:
        """Return None when the wheel cannot run here."""
        if "any" in platform_tag:
            platform_score = 1
        elif PLATFORM in platform_tag:
            platform_score = 3
        else:
            return None

        if abi_tag == "none":
            abi_score = 3
        elif abi_tag == "abi3":
            abi_score = 3
        elif abi_tag == PY:
            abi_score = 3
        else:
            return None

        if py_tag in (PY, "py3", "py2.py3"):
            py_score = 3
        elif py_tag.startswith("cp") and py_tag != PY:
            return None
        elif py_tag.startswith("py3"):
            py_score = 2
        else:
            return None

        return platform_score * 10 + abi_score * 3 + py_score

    def pick(self, name: str, spec: str | None, allow_prerelease: bool) -> tuple[Version, str, str]:
        """Pick the best wheel for `name` honouring `spec` (a version specifier string)."""
        html = self.index(name)
        candidates: list[tuple[int, Version, str, str]] = []
        for href in re.findall(r'href="([^"#]+\.whl)', html):
            bare = href.rsplit("/", 1)[-1]
            try:
                dist, version, build, tags = parse_wheel_filename(bare)
            except Exception:  # noqa: BLE001 - unparseable filename
                continue
            if canonicalize_name(str(dist)) != canonicalize_name(name):
                continue
            if not allow_prerelease and (version.is_prerelease or version.is_devrelease):
                continue
            if spec:
                from packaging.specifiers import SpecifierSet

                if version not in SpecifierSet(spec):
                    continue
            score = None
            for tag in tags:  # frozenset of packaging.tags.Tag
                tag_score = self._score(tag.platform, tag.abi, tag.interpreter)
                if tag_score is not None and (score is None or tag_score > score):
                    score = tag_score
            if score is None:
                continue
            url = href if href.startswith("http") else MIRRORS[0].rsplit("/simple", 1)[0] + "/" + href.lstrip("./")
            candidates.append((score, version, url, bare))

        if not candidates:
            raise RuntimeError(f"no compatible wheel for {name}{spec or ''}")

        # newest version first, then best tag score
        candidates.sort(key=lambda c: (c[1], c[0]), reverse=True)
        _, version, url, filename = candidates[0]
        return version, url, filename

    # ------------------------------------------------------------ metadata ---
    @staticmethod
    def metadata(blob: bytes) -> tuple[str, list[str]]:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            meta_name = next(
                (n for n in zf.namelist() if n.endswith(".dist-info/METADATA")), None
            )
            if not meta_name:
                raise RuntimeError("wheel has no METADATA")
            text = zf.read(meta_name).decode("utf-8", "replace")
        reqs = []
        for line in text.splitlines():
            if line.lower().startswith("requires-dist:"):
                reqs.append(line.split(":", 1)[1].strip())
        return text, reqs

    # ------------------------------------------------------------- resolve ---
    def resolve(self, specs: list[str]) -> list[tuple[str, Version, str, str]]:
        """Breadth-first resolution. Returns install order (deps first)."""
        queue: list[Requirement] = [Requirement(s) for s in specs]
        chosen: dict[str, tuple[Version, str, str]] = {}
        order: list[str] = []
        env = default_environment() | {"extra": ""}

        while queue:
            req = queue.pop(0)
            key = canonicalize_name(req.name)
            if key in chosen:
                continue

            spec = str(req.specifier) if str(req.specifier) else None
            allow_pre = any(s in (spec or "") for s in ("dev", "rc", "a", "b"))
            version, url, filename = self.pick(req.name, spec, allow_pre)

            resp = requests.get(url, timeout=300)
            resp.raise_for_status()
            blob = resp.content
            _, requires = self.metadata(blob)

            chosen[key] = (version, url, filename)
            order.append(key)
            self._blobs = getattr(self, "_blobs", {})
            self._blobs[key] = blob
            print(f"  ✓ {req.name} {version}  ({len(blob)/1024/1024:.1f} MB)")

            for line in requires:
                try:
                    child = Requirement(line)
                except Exception:  # noqa: BLE001
                    continue
                if child.marker is not None:
                    extras = child.marker.evaluate(env | {"extra": ""})
                    if not extras:
                        # maybe the marker is only true for an extra we asked for
                        wanted = [e for e in req.extras]
                        if not wanted:
                            continue
                        if not any(child.marker.evaluate(env | {"extra": e}) for e in wanted):
                            continue
                queue.append(child)

        return [(name, *chosen[name]) for name in order]

    def blobs(self) -> dict[str, bytes]:
        return getattr(self, "_blobs", {})


def install(target: Path, resolved: list[tuple[str, Version, str, str]], blobs: dict[str, bytes]) -> None:
    target.mkdir(parents=True, exist_ok=True)
    total = 0
    for name, version, url, filename in resolved:
        blob = blobs[name]
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            for member in zf.infolist():
                if member.filename.endswith("/"):
                    continue
                if "/__pycache__/" in member.filename:
                    continue
                path = target / member.filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(zf.read(member))
                total += 1
    print(f"\n写入了 {total} 个文件 -> {target}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("specs", nargs="+", help="如 flet==1.0.4 或 pyinstaller")
    parser.add_argument("--target", required=False, help="安装到哪个 site-packages")
    parser.add_argument("--list", action="store_true", help="只解析依赖，不安装")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    print("解析依赖…")
    resolver = Resolver()
    resolved = resolver.resolve(args.specs)
    print(f"\n共 {len(resolved)} 个包")
    for name, version, url, filename in resolved:
        print(f"  {name:<32} {version}")

    if args.list:
        return 0
    if not args.target:
        print("需要 --target", file=sys.stderr)
        return 2
    install(Path(args.target), resolved, resolver.blobs())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
