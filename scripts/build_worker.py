"""Pinned upstream jars, checksum-verified; no Maven service required at runtime."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    lib = ROOT / "worker/lib"
    lib.mkdir(parents=True, exist_ok=True)
    lock = json.loads((ROOT / "worker/dependencies.lock.json").read_text())
    for item in lock:
        dest = lib / item["file"]
        if not dest.exists():
            urllib.request.urlretrieve(item["url"], dest)
        digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        if digest != item["sha256"]:
            raise RuntimeError(f"checksum mismatch: {dest.name}")
    (ROOT / "worker/build").mkdir(exist_ok=True)
    javac = str(Path(os.environ["JAVA_HOME"]) / "bin/javac") if os.getenv("JAVA_HOME") else "javac"
    subprocess.run([javac, "--release", "21", "-cp", str(lib / "*"), "-d", str(ROOT / "worker/build"), str(ROOT / "worker/src/PaymentWorker.java")], check=True)


if __name__ == "__main__":
    main()
