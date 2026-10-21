#!/usr/bin/env python3
"""Install lightcraft-cli on Linux: Claude's cloud sandbox (a chat in the Claude apps, a Managed Agents
session) or a Linux server. Downloads LightCraft's own Linux release from its GitHub release page, checks it
against the SHA-256 pinned below, and puts lightcraft-cli in ~/.lightcraft-skill/bin/, where lc.py finds it.

On a Mac the user installs lightcraft-cli themselves (`lc.py cli-info` names the file); this script refuses
there. The release URL below is its only network use. Standard library only.

    install_cli.py                  download the pinned release, check it, install
    install_cli.py --tarball FILE   the same release tarball, already on disk (a session upload, a Docker build)
"""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ in the skill's folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lc

RELEASE = "0.9.1"
# From that release's SHA256SUMS.txt. Another release takes --release and --sha256 together.
SHA256 = {
    "x86_64": "7f6297d3a159aa391b13aac049397730305cc04a8dbf12ab0ff61f86f551f7a9",
    "aarch64": "323dc7cb021bc5ca8dddd9ac66420073a7ddaa15cab705168b353c160b10a916",
}
URL = "https://github.com/storytold/lightcraft/releases/download/v{release}/{name}"
ARCH = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}


def cli_version(path):
    """(`lightcraft-cli --version` output, None), or (None, the error that kept it from running)."""
    try:
        r = subprocess.run([str(path), "--version"], capture_output=True, text=True, timeout=60)
    except OSError as e:
        return None, str(e)
    if r.returncode:
        return None, (r.stderr or r.stdout).strip()
    return r.stdout.strip(), None


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "lightcraft-skill"})
    with urllib.request.urlopen(req, timeout=600) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tarball", help="lightcraft-<release>-linux-<arch>.tar.gz already on disk, instead of downloading it")
    ap.add_argument("--release", help=f"a LightCraft release other than {RELEASE}; needs --sha256")
    ap.add_argument("--sha256", help="that release's tarball SHA-256, from its SHA256SUMS.txt")
    ap.add_argument("--force", action="store_true", help="reinstall even if this release is already installed")
    a = ap.parse_args()

    if not sys.platform.startswith("linux"):
        lc.die("install_cli.py is for Linux. On a Mac, install lightcraft-cli yourself: `lc.py cli-info` names the file.")
    if bool(a.release) != bool(a.sha256):
        lc.die("--release and --sha256 go together")
    arch = ARCH.get(platform.machine().lower())
    if not arch:
        lc.die(f"this installer covers LightCraft's x86_64 and aarch64 Linux builds, not {platform.machine()}")
    release = a.release or RELEASE
    expected = (a.sha256 or SHA256[arch]).lower()
    name = f"lightcraft-{release}-linux-{arch}.tar.gz"
    target = lc.BIN_DIR / "lightcraft-cli"

    if target.exists() and not a.force:
        ver, _ = cli_version(target)
        if ver and release in ver.split():
            print(json.dumps({"installed": str(target), "version": ver, "alreadyInstalled": True}))
            return

    with tempfile.TemporaryDirectory() as td:
        tarball = Path(a.tarball).expanduser() if a.tarball else Path(td) / name
        if not a.tarball:
            url = URL.format(release=release, name=name)
            try:
                download(url, tarball)
            except OSError as e:  # URLError and HTTPError are OSErrors
                lc.die(f"cannot download {url} ({e}). A chat sandbox may reach github.com but not the host GitHub "
                       "serves release files from: ask the user to turn on network access (Settings > Capabilities), "
                       "or pass the same tarball with --tarball.")
        digest = sha256(tarball)
        if digest != expected:
            lc.die(f"{tarball.name}: SHA-256 {digest} is not the release's {expected}; not installing it")
        with tarfile.open(tarball) as t:
            member = next((m for m in t.getmembers() if m.isfile() and m.name.endswith("/bin/lightcraft-cli")), None)
            if member is None:
                lc.die(f"{tarball.name} has no bin/lightcraft-cli")
            lc.HOME.mkdir(mode=0o700, parents=True, exist_ok=True)
            lc.BIN_DIR.mkdir(exist_ok=True)
            part = target.with_name("lightcraft-cli.part")
            with t.extractfile(member) as src, open(part, "wb") as dst:
                shutil.copyfileobj(src, dst)
            part.chmod(0o755)
            part.replace(target)

    ver, err = cli_version(target)
    if not ver:
        hint = " LightCraft's Linux build needs glibc 2.35 or newer." if "GLIBC" in err else ""
        lc.die(f"lightcraft-cli is installed but doesn't run here: {err}.{hint}")
    print(json.dumps({"installed": str(target), "release": release, "sha256": digest, "version": ver}))


if __name__ == "__main__":
    main()
