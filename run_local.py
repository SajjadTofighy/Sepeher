#!/usr/bin/env python3
"""Cross-platform launcher for the prebuilt React UI and local Python mock API."""

import argparse
import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Run Sepehr local demo")
    parser.add_argument("--host", default="0.0.0.0", help="Interface to listen on")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--demo", action="store_true", help="Explicitly enable unauthenticated demo mode")
    parser.add_argument(
        "--no-install",
        action="store_true",
        help="Use the existing virtual environment without installing",
    )
    args = parser.parse_args()
    if args.demo:
        os.environ["SEPEHR_AUTH_MODE"] = "demo"
    if sys.version_info < (3, 10):
        raise SystemExit("Python 3.10 or newer is required.")
    if not (ROOT / "frontend/dist/index.html").exists():
        raise SystemExit(
            "Missing frontend build. Run: npm ci --prefix frontend && npm run build --prefix frontend"
        )
    env = ROOT / ".venv"
    python = env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        if args.no_install:
            raise SystemExit(
                "Virtual environment missing. Run without --no-install once."
            )
        print("Creating local Python environment...", flush=True)
        venv.create(env, with_pip=True)
    requirements = ROOT / "backend/requirements.txt"
    if not args.no_install:
        subprocess.run(
            [str(python), "-m", "pip", "install", "-r", str(requirements)], check=True
        )
    print(
        f"\nListening on {args.host}:{args.port}\nSepehr demo: http://127.0.0.1:{args.port}\nAPI docs: http://127.0.0.1:{args.port}/docs\nFor LAN access, use this machine's network IP instead of 127.0.0.1.\nPress Ctrl+C to stop.\n",
        flush=True,
    )
    try:
        subprocess.run(
            [
                str(python),
                "-m",
                "uvicorn",
                "app.main:app",
                "--app-dir",
                str(ROOT / "backend"),
                "--host",
                args.host,
                "--port",
                str(args.port),
                "--workers",
                "1",
            ],
            cwd=ROOT,
            check=True,
        )
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
