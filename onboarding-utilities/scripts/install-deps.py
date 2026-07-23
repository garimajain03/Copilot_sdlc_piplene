#!/usr/bin/env python3
"""
install-deps.py — Download otelcol-contrib and prometheus binaries to a local
project directory (.github/observability/.bin/). No sudo required.

Usage:
    python3 install-deps.py                  # Install both
    python3 install-deps.py --check          # Check if binaries are present
    python3 install-deps.py --json           # Output result as JSON (for setup.sh)

Binaries are downloaded from official GitHub releases and placed in:
    .github/observability/.bin/otelcol-contrib
    .github/observability/.bin/prometheus
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import urllib.error
import zipfile
from pathlib import Path

# ─── Configuration ───────────────────────────────────────────────────────────

OTELCOL_VERSION = "0.151.0"
PROMETHEUS_VERSION = "3.4.1"

SCRIPT_DIR = Path(__file__).resolve().parent
BIN_DIR = SCRIPT_DIR.parent / ".bin"

# Map platform.machine() to release archive arch names
ARCH_MAP = {
    "arm64": "arm64",
    "aarch64": "arm64",
    "x86_64": "amd64",
    "AMD64": "amd64",
}

# ─── Helpers ─────────────────────────────────────────────────────────────────

def log(msg: str):
    print(f"  {msg}", file=sys.stderr)


def get_arch() -> str:
    machine = platform.machine()
    arch = ARCH_MAP.get(machine)
    if not arch:
        raise RuntimeError(f"Unsupported architecture: {machine}")
    return arch


def get_os() -> str:
    system = platform.system().lower()
    if system not in ("darwin", "linux"):
        raise RuntimeError(f"Unsupported OS: {system}")
    return system


def download_file(url: str, dest: Path) -> bool:
    """Download a URL to a local file. Tries urllib first, falls back to curl."""
    log(f"Downloading: {url}")

    # Try urllib first
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "intl-dev-setup/1.0")
        with urllib.request.urlopen(req, timeout=120) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 1024 * 256  # 256KB chunks
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = downloaded * 100 // total
                        mb = downloaded / (1024 * 1024)
                        total_mb = total / (1024 * 1024)
                        print(
                            f"\r  [{pct:3d}%] {mb:.1f} / {total_mb:.1f} MB",
                            end="", file=sys.stderr, flush=True,
                        )
            if total > 0:
                print(file=sys.stderr)  # newline after progress
        return True
    except urllib.error.URLError as e:
        if "CERTIFICATE_VERIFY_FAILED" in str(e) or "SSL" in str(e):
            log("SSL error with urllib, falling back to curl...")
            return _download_with_curl(url, dest)
        log(f"Download failed: {e}")
        return False
    except (urllib.error.HTTPError, OSError) as e:
        log(f"Download failed: {e}")
        return False


def _download_with_curl(url: str, dest: Path) -> bool:
    """Download using curl (uses system certificate store, avoids Python SSL issues)."""
    try:
        result = subprocess.run(
            ["curl", "-fSL", "--progress-bar", "-o", str(dest), url],
            timeout=300,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        log(f"curl download failed: {e}")
        return False


def extract_binary(archive_path: Path, binary_name: str, dest_dir: Path) -> Path | None:
    """Extract a named binary from a tar.gz or zip archive."""
    dest_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        if str(archive_path).endswith(".tar.gz") or str(archive_path).endswith(".tgz"):
            with tarfile.open(archive_path, "r:gz") as tf:
                tf.extractall(tmp_path, filter="data" if hasattr(tarfile, "data_filter") else None)
        elif str(archive_path).endswith(".zip"):
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(tmp_path)
        else:
            log(f"Unknown archive format: {archive_path}")
            return None

        # Find the binary (may be at root or in a subdirectory)
        for candidate in tmp_path.rglob(binary_name):
            if candidate.is_file():
                dest = dest_dir / binary_name
                shutil.copy2(candidate, dest)
                dest.chmod(0o755)
                return dest

    log(f"Binary '{binary_name}' not found in archive")
    return None


# ─── Installers ──────────────────────────────────────────────────────────────

def install_otelcol(arch: str, os_name: str) -> dict:
    """Download and install otelcol-contrib."""
    binary_path = BIN_DIR / "otelcol-contrib"

    if binary_path.exists():
        log(f"otelcol-contrib already installed at {binary_path}")
        return {"name": "otelcol-contrib", "status": "already_installed", "path": str(binary_path)}

    url = (
        f"https://github.com/open-telemetry/opentelemetry-collector-releases/"
        f"releases/download/v{OTELCOL_VERSION}/"
        f"otelcol-contrib_{OTELCOL_VERSION}_{os_name}_{arch}.tar.gz"
    )

    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "otelcol-contrib.tar.gz"
        if not download_file(url, archive):
            return {"name": "otelcol-contrib", "status": "download_failed", "url": url}

        result = extract_binary(archive, "otelcol-contrib", BIN_DIR)
        if result:
            log(f"otelcol-contrib v{OTELCOL_VERSION} installed to {result}")
            return {"name": "otelcol-contrib", "status": "installed", "path": str(result), "version": OTELCOL_VERSION}
        else:
            return {"name": "otelcol-contrib", "status": "extract_failed"}


def install_prometheus(arch: str, os_name: str) -> dict:
    """Download and install prometheus."""
    binary_path = BIN_DIR / "prometheus"

    if binary_path.exists():
        log(f"prometheus already installed at {binary_path}")
        return {"name": "prometheus", "status": "already_installed", "path": str(binary_path)}

    url = (
        f"https://github.com/prometheus/prometheus/"
        f"releases/download/v{PROMETHEUS_VERSION}/"
        f"prometheus-{PROMETHEUS_VERSION}.{os_name}-{arch}.tar.gz"
    )

    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "prometheus.tar.gz"
        if not download_file(url, archive):
            return {"name": "prometheus", "status": "download_failed", "url": url}

        result = extract_binary(archive, "prometheus", BIN_DIR)
        if result:
            log(f"prometheus v{PROMETHEUS_VERSION} installed to {result}")
            return {"name": "prometheus", "status": "installed", "path": str(result), "version": PROMETHEUS_VERSION}
        else:
            return {"name": "prometheus", "status": "extract_failed"}


# ─── Check Mode ──────────────────────────────────────────────────────────────

def check_binaries() -> dict:
    """Check if binaries are present (in .bin/ or on PATH)."""
    results = {}
    for name in ("otelcol-contrib", "prometheus"):
        local_path = BIN_DIR / name
        if local_path.exists():
            results[name] = {"available": True, "path": str(local_path), "source": "local"}
        elif shutil.which(name):
            results[name] = {"available": True, "path": shutil.which(name), "source": "PATH"}
        else:
            results[name] = {"available": False}
    return results


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    json_mode = "--json" in sys.argv
    check_mode = "--check" in sys.argv

    if check_mode:
        result = check_binaries()
        if json_mode:
            print(json.dumps(result))
        else:
            for name, info in result.items():
                if info["available"]:
                    log(f"✓ {name}: {info['path']} ({info['source']})")
                else:
                    log(f"✗ {name}: not found")
        all_available = all(v["available"] for v in result.values())
        sys.exit(0 if all_available else 1)

    try:
        arch = get_arch()
        os_name = get_os()
    except RuntimeError as e:
        if json_mode:
            print(json.dumps({"error": str(e)}))
        else:
            log(f"Error: {e}")
        sys.exit(1)

    log(f"Platform: {os_name}/{arch}")
    log(f"Install directory: {BIN_DIR}")
    BIN_DIR.mkdir(parents=True, exist_ok=True)

    results = []

    log("")
    log("─── Installing otelcol-contrib ───")
    results.append(install_otelcol(arch, os_name))

    log("")
    log("─── Installing prometheus ───")
    results.append(install_prometheus(arch, os_name))

    if json_mode:
        print(json.dumps({"results": results, "bin_dir": str(BIN_DIR)}))
    else:
        log("")
        log("─── Summary ───")
        all_ok = True
        for r in results:
            status = r["status"]
            if status in ("installed", "already_installed"):
                log(f"✓ {r['name']}: {r.get('path', 'OK')}")
            else:
                log(f"✗ {r['name']}: {status}")
                all_ok = False

        if all_ok:
            log("")
            log(f"Binaries are in: {BIN_DIR}")
            log("The observability hooks will find them automatically.")

    sys.exit(0 if all(r["status"] in ("installed", "already_installed") for r in results) else 1)


if __name__ == "__main__":
    main()
