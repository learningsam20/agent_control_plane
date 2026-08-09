"""Example 4 — Tamper-evident audit chain.

Verifies the integrity of the hash chain and demonstrates tamper detection:
mutating a stored block (simulated) is immediately caught by recomputing the
chain, which also invalidates every subsequent block.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "sdk"))

import httpx  # noqa: E402

from controlplane import ControlPlaneClient, default_base_url  # noqa: E402

BASE_URL = default_base_url()


def main() -> None:
    cp = ControlPlaneClient(base_url=BASE_URL)

    report = cp.verify_chain()
    print("=== Audit chain integrity ===\n")
    print(f"  blocks: {report['block_count']}")
    print(f"  head:   {report['head'][:20]}…")
    print(f"  valid:  {report['valid']}\n")

    if report["block_count"] == 0:
        print("No blocks yet — run examples 01/02/03 first to build history.")
        return

    seq = report["block_count"]
    print(f"Simulating a tamper on block seq={seq} …")
    httpx.post(f"{BASE_URL}/api/audit/simulate-tamper", params={"seq": seq})

    after = cp.verify_chain()
    print(f"  valid after tamper: {after['valid']}")
    for issue in after["issues"][:5]:
        print(f"  issue @ seq {issue['seq']}: {issue['kind']} — {issue['detail'][:60]}")

    print("\nThe control plane exposes this check to the console (Audit → Verify chain)")
    print("and to any external auditor via GET /api/audit/verify/chain.")


if __name__ == "__main__":
    main()
