#!/usr/bin/env python3
"""Submit one rendered entry through prodtools submit_entry.

Runs under the sourced Mu2e env (prodtools utils import samweb_client),
cwd = the stage dir holding the cnf tarball. Prints one line:
SUBMIT_RESULT {"cluster_id": ..., "jobsub_id": ..., "status": ...}
The ledger row lifecycle (reserve -> attach / fail) is submit_entry's
own -- a failed submission closes its reservation before we exit.

Verified against /exp/mu2e/app/users/oksuzian/muse_050125/prodtools
(read-only checkout) 2026-08-16:
- utils/submission_ledger.ensure_ledger_dir(db_path) mkdir's db_path's
  PARENT and returns db_path unchanged -- but its docstring says it is
  "Called ONLY on a ledger_for() path" (a per-user DERIVED default);
  an operator-supplied/explicit path (which --ledger is, from this
  driver's perspective) is documented to arrive "exactly as given",
  deliberately never auto-mkdir'd, so a typo fails loudly instead of
  silently creating a stray DB (utils/submit.py:_reserve_in_ledger
  docstring). --ledger here is autoresearch's own derived path
  (DATA_ROOT/prodtools_ledger/submissions.db), not a typo-prone
  operator flag, so we mkdir its parent ourselves and pass args.ledger
  straight to SubmitOptions rather than call the ledger_for()-only
  helper against its documented contract.
- utils/submit.py SubmitOptions is a NamedTuple with `ledger_db`
  (required, no default), `dry_run` (bool, default False), `origin`
  (Optional[str], default None), `wftop`/`wfproject` (Optional[str],
  default None) -- all four fields the brief assumed are present with
  those exact names.
- utils/submit.py submit_entry(entry, idx, options) returns a dict
  with (at least) `cluster_id`, `jobsub_id`, `status` -- confirmed at
  utils/submit.py:695-876. `cluster_id` is a numeric STRING (parsed via
  regex from jobsub_submit stdout), not an int; `jobsub_id` is the full
  "CLUSTER.PROC@schedd" string or None. Both match what
  core/prodtools_exec.py:submit_cnf already expects (it does
  int(data["cluster_id"]) and strips ".PROC" itself).
"""
import argparse
import json
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prodtools", required=True)
    ap.add_argument("--entry", required=True)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--origin", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sys.path.insert(0, args.prodtools)
    from utils.submit import SubmitOptions, submit_entry

    entry = json.loads(open(args.entry).read())[0]
    # args.ledger is a derived-but-not-ledger_for() path (see module
    # docstring): create its parent ourselves rather than call
    # submission_ledger.ensure_ledger_dir, which is documented for the
    # per-user default path only.
    Path(args.ledger).parent.mkdir(parents=True, exist_ok=True)
    opts = SubmitOptions(ledger_db=args.ledger, dry_run=args.dry_run,
                         origin=args.origin,
                         wftop="/pnfs/mu2e/scratch/users",
                         wfproject="default")
    result = submit_entry(entry, 0, opts)
    print("SUBMIT_RESULT " + json.dumps({
        "cluster_id": result.get("cluster_id"),
        "jobsub_id": result.get("jobsub_id"),
        "status": result.get("status"),
    }), flush=True)
    return 0 if result.get("cluster_id") else 1


if __name__ == "__main__":
    sys.exit(main())
