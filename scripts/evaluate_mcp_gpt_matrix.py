#!/usr/bin/env python3
"""Run six MCP acceptance cases for all advertised models matching a prefix.

Each model gets separate server processes, job directories and evidence files.
No failed case is retried or replaced. Models run with bounded concurrency;
cases within each model are sequential. This is an opt-in live test, not CI.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import re
import statistics
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import httpx
from evaluate_mcp_gpt import (
    CASES,
    SYSTEM,
    EvaluationError,
    describe_failure,
    evaluate,
    read_api_key,
    write_json,
)


def summarize(report, elapsed):
    rows = report["cases"]
    requests = [r for c in rows for r in c["requests"]]
    latencies = [r["latency_seconds"] for r in requests]
    usage = [r.get("usage", {}) for r in requests]
    return {
        "model": report["requested_model"],
        "returned_models": sorted({r["model"] for r in requests if r.get("model")}),
        "passed": sum(c["passed"] for c in rows),
        "total": len(rows),
        "assertions_passed": sum(sum(c["checks"].values()) for c in rows),
        "assertions_total": sum(len(c["checks"]) for c in rows),
        "elapsed_seconds": round(elapsed, 3),
        "requests": len(requests),
        "http_errors": sum(
            r["http_status"] is not None and r["http_status"] >= 400 for r in requests
        ),
        "transport_errors": sum(r["http_status"] is None for r in requests),
        "median_request_seconds": round(statistics.median(latencies), 3)
        if latencies
        else None,
        "input_tokens": sum(u.get("prompt_tokens", 0) for u in usage),
        "output_tokens": sum(u.get("completion_tokens", 0) for u in usage),
        "total_tokens": sum(u.get("total_tokens", 0) for u in usage),
        "cached_input_tokens": sum(
            u.get("prompt_tokens_details", {}).get("cached_tokens", 0) for u in usage
        ),
        "cases": [
            {
                "id": c["id"],
                "passed": c["passed"],
                "failed_checks": [k for k, v in c["checks"].items() if not v],
                "error": c["error"],
            }
            for c in rows
        ],
    }


def verify_artifacts(report):
    """Independently check the persisted outputs behind successful tool results."""
    manifests, artifacts = set(), set()
    for case in report["cases"]:
        transcript = json.loads(Path(case["transcript"]).read_text())
        for call in transcript["calls"]:
            view = call["result"]
            if (
                call["name"] != "get_run"
                or call["is_error"]
                or view.get("status") != "completed"
            ):
                continue
            manifest_path = Path(view["manifest_path"])
            manifest = json.loads(manifest_path.read_text())
            if manifest["status"] != "completed" or manifest["mode"] != "mock":
                raise ValueError("Unexpected persisted run status or mode")
            manifests.add(str(manifest_path))
            for artifact in view["artifacts"]:
                path = Path(artifact["path"])
                path.resolve().relative_to(manifest_path.parent.resolve())
                data = path.read_bytes()
                if (
                    len(data) != artifact["size_bytes"]
                    or hashlib.sha256(data).hexdigest() != artifact["sha256"]
                ):
                    raise ValueError("Artifact size or SHA-256 mismatch")
                artifacts.add(str(path))
    return {"passed": True, "manifests": len(manifests), "artifacts": len(artifacts)}


async def matrix(args):
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise ValueError("Use an empty --output-dir to preserve previous results")
    key = read_api_key(args)
    async with httpx.AsyncClient(timeout=args.timeout, trust_env=False) as http:
        result = await http.get(
            args.base_url.rstrip("/") + "/models",
            headers={"Authorization": f"Bearer {key}"},
        )
        if not result.is_success:
            raise EvaluationError(f"LLM model discovery HTTP {result.status_code}")
        available = sorted({m["id"] for m in result.json()["data"]})
    models = [
        m
        for m in available
        if m.startswith(args.model_prefix)
        and not any(m.startswith(p) for p in args.exclude_prefix)
    ]
    if not models:
        raise EvaluationError("Provider advertised no models matching the filters")
    if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", m) for m in models):
        raise EvaluationError("Selected model ID is not a safe evidence filename")
    summary = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "python": platform.python_version(),
        "mcp_sdk": version("mcp"),
        "available_models": available,
        "model_discovery_http_status": result.status_code,
        "selected_models": models,
        "excluded_models": {
            m: "excluded by model-prefix or exclude-prefix filter"
            for m in available
            if m not in models
        },
        "settings": {
            "workers": args.workers,
            "timeout_seconds": args.timeout,
            "max_rounds": args.max_rounds,
            "max_tokens": args.max_tokens,
            "model_prefix": args.model_prefix,
            "exclude_prefix": args.exclude_prefix,
            "preserve_reasoning": args.preserve_reasoning,
            "thinking": "omitted (provider default)",
            "temperature": "omitted (provider default)",
            "reasoning_effort": "omitted (provider default)",
            "cases": list(CASES),
            "repeats": 1,
            "retries": 0,
            "live_llm": True,
            "science_mode": "mock",
            "fallback": False,
        },
        "script_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (Path(__file__), Path(__file__).with_name("evaluate_mcp_gpt.py"))
        },
        "scenario_sha256": hashlib.sha256(
            json.dumps({"system": SYSTEM, "cases": CASES}, sort_keys=True).encode()
        ).hexdigest(),
        "product_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(
                (Path(__file__).resolve().parents[1] / "src/ml4gw_agent").glob("*.py")
            )
        },
        "status": "running",
        "models": [],
    }
    path = args.output_dir / "summary.json"
    write_json(path, summary)
    slots = asyncio.Semaphore(args.workers)
    started = time.monotonic()

    async def run(model):
        async with slots:
            before = time.monotonic()
            output = args.output_dir / f"{model}.json"
            options = argparse.Namespace(
                base_url=args.base_url,
                model=model,
                api_key_env=args.api_key_env,
                proxy_config=args.proxy_config,
                key_file=args.key_file,
                case=None,
                max_rounds=args.max_rounds,
                max_tokens=args.max_tokens,
                preserve_reasoning=args.preserve_reasoning,
                timeout=args.timeout,
                runs_dir=args.runs_dir / model,
                output=output,
            )
            print(f"[{model}] BEGIN", flush=True)
            try:
                await evaluate(options)
                report = json.loads(output.read_text())
                row = summarize(report, time.monotonic() - before)
                try:
                    row["artifact_verification"] = verify_artifacts(report)
                except Exception as exc:
                    row["artifact_verification"] = {
                        "passed": False,
                        "error": describe_failure(exc),
                    }
                row["report"] = output.name
            except Exception as exc:
                row = {
                    "model": model,
                    "error": describe_failure(exc),
                    "passed": 0,
                    "total": len(CASES),
                    "report": output.name if output.exists() else None,
                }
            summary["models"].append(row)
            summary["models"].sort(key=lambda r: r["model"])
            write_json(path, summary)
            print(f"[{model}] FINISHED {row['passed']}/{row['total']}", flush=True)

    await asyncio.gather(*(run(m) for m in models))
    summary["status"] = "completed"
    summary["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    summary["elapsed_seconds"] = round(time.monotonic() - started, 3)
    summary["passed_cases"] = sum(r["passed"] for r in summary["models"])
    summary["total_cases"] = len(models) * len(CASES)
    summary["all_passed"] = all(
        r["passed"] == len(CASES) and r.get("artifact_verification", {}).get("passed")
        for r in summary["models"]
    )
    write_json(path, summary)
    print(
        f"Matrix: {summary['passed_cases']}/{summary['total_cases']} -> {path}",
        flush=True,
    )
    return 0 if summary["all_passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8317/v1")
    parser.add_argument("--api-key-env", default="ML4GW_LLM_API_KEY")
    credentials = parser.add_mutually_exclusive_group()
    credentials.add_argument("--proxy-config", type=Path)
    credentials.add_argument("--key-file", type=Path)
    parser.add_argument("--model-prefix", default="gpt-")
    parser.add_argument("--exclude-prefix", action="append", default=["gpt-image-"])
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--max-rounds", type=int, default=16)
    parser.add_argument("--max-tokens", type=int, default=2500)
    parser.add_argument("--preserve-reasoning", action="store_true")
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--runs-dir", type=Path, default=Path("runs/mcp-gpt-matrix"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if (
        args.workers < 1
        or args.max_rounds < 1
        or args.max_tokens < 1
        or args.timeout <= 0
    ):
        parser.error("workers, max-rounds, max-tokens and timeout must be positive")
    return asyncio.run(matrix(args))


if __name__ == "__main__":
    raise SystemExit(main())
