#!/usr/bin/env python3
"""Full demo runner: wipes the database, boots the API, and runs every example."""

import os
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend")
EXAMPLES = os.path.join(ROOT, "examples")
DB_PATH = os.path.join(BACKEND, "data", "controlplane.db")
KEY_DIR = os.path.join(BACKEND, "data", "demo_agents")
CRED_DIR = os.path.join(BACKEND, "data", "agents")
LOG = "/tmp/controlplane.log"

# Port comes from the same config the server reads (env `PORT`, default 5186).
HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "5186"))
BASE = f"http://{HOST}:{PORT}"


def main() -> int:
    for path in (DB_PATH, KEY_DIR, CRED_DIR):
        if os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)

    env = dict(os.environ, PORT=str(PORT))
    server = subprocess.Popen(
        ["python3", "run.py"],
        cwd=BACKEND,
        env=env,
        stdout=open(LOG, "w"),
        stderr=subprocess.STDOUT,
    )
    print(f"control plane booting on {BASE} …")
    try:
        for _ in range(30):
            try:
                urllib.request.urlopen(f"{BASE}/health", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            print("server did not become ready — see", LOG)
            return 1

        examples = sorted(f for f in os.listdir(EXAMPLES) if f.endswith(".py"))
        for name in examples:
            print(f"\n=== {name} ===")
            rc = subprocess.call([sys.executable, os.path.join(EXAMPLES, name)], cwd=ROOT)
            if rc != 0:
                print(f"FAILED {name} (rc={rc})")
                return rc
        print("\nAll examples ran successfully.")
        return 0
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    sys.exit(main())
