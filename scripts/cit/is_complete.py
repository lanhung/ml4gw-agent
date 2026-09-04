#!/usr/bin/env python3
"""Exit 0 if any run manifest under the given event directory is completed."""

import glob
import json
import sys

ok = any(
    json.load(open(f)).get("status") == "completed"
    for f in glob.glob(sys.argv[1] + "/submission_*/worker/run_*/run_manifest.json")
)
sys.exit(0 if ok else 1)
