#!/usr/bin/env python3
"""Pin every price-check cron job to a model (default: Claude Haiku 5.5).

Runs on the HOST (ZORO, as zoro), not in the sandbox. Hermes deliberately
doesn't let the agent choose a job's model, so this does it with the CLI:

    hermes -p <profile> cron edit <job_id> --model <model>

It reads products.json and only edits jobs whose recorded `cron_model` differs,
so it's quiet and safe to run from crontab. Standard library only.

    python3 ~/price-check/host/pin_models.py            # apply
    python3 ~/price-check/host/pin_models.py --dry-run  # show what it would do

Exit codes: 0 ok (or nothing to do), 1 one or more edits failed, 2 setup error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None


def find_hermes(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    for cand in (shutil.which("hermes"), str(Path.home() / ".local/bin/hermes")):
        if cand and Path(cand).exists():
            return cand
    return None


def write_json(path: Path, data) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", default=os.environ.get("PRICE_CHECK_MODEL", "claude-haiku-5-5"))
    ap.add_argument("--profile", default="assistant")
    ap.add_argument("--home", default=os.environ.get("PRICE_CHECK_HOME",
                                                     str(Path.home() / "price-check-data")))
    ap.add_argument("--hermes", help="path to the hermes CLI (default: found on PATH)")
    ap.add_argument("--force", action="store_true", help="re-pin even if already recorded")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    home = Path(a.home).expanduser()
    products_file = home / "products.json"
    if not products_file.exists():
        return 0  # nothing tracked yet
    hermes = find_hermes(a.hermes)
    if not hermes:
        print("error: hermes CLI not found; pass --hermes /path/to/hermes", file=sys.stderr)
        return 2

    lock = open(home / ".lock", "a")
    if fcntl:
        fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        data = json.loads(products_file.read_text(encoding="utf-8"))
        todo = [p for p in data.get("products", [])
                if p.get("cron_job_id") and (a.force or p.get("cron_model") != a.model)]
        failed = 0
        for p in todo:
            cmd = [hermes, "-p", a.profile, "cron", "edit", p["cron_job_id"], "--model", a.model]
            stamp = dt.datetime.now().astimezone().replace(microsecond=0).isoformat()
            if a.dry_run:
                print(f"would run: {' '.join(cmd)}   # {p['name']}")
                continue
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if r.returncode == 0:
                p["cron_model"] = a.model
                print(f"{stamp} pinned {p['cron_job_id']} ({p['name']}) to {a.model}")
            else:
                failed += 1
                err = (r.stderr or r.stdout).strip().splitlines()[-1:] or ["(no output)"]
                print(f"{stamp} FAILED {p['cron_job_id']} ({p['name']}): {err[0]}", file=sys.stderr)
        if todo and not a.dry_run:
            write_json(products_file, data)
        return 1 if failed else 0
    finally:
        if fcntl:
            fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


if __name__ == "__main__":
    sys.exit(main())
