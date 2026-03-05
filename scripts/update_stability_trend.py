from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_history(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def build_entry(report: Dict[str, Any], source_file: str) -> Dict[str, Any]:
    trend = report.get("trend", {})
    return {
        "timestamp_utc": report.get("timestamp_utc") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": report.get("status", "unknown"),
        "duration_minutes": report.get("duration_minutes", 0),
        "iterations": report.get("iterations", 0),
        "degraded_iterations": report.get("degraded_iterations", 0),
        "error_rate_avg": trend.get("error_rate", {}).get("avg", 0.0),
        "error_rate_max": trend.get("error_rate", {}).get("max", 0.0),
        "latency_p95_avg_ms": trend.get("latency_p95_ms", {}).get("avg", 0.0),
        "latency_p95_max_ms": trend.get("latency_p95_ms", {}).get("max", 0.0),
        "source_file": source_file,
    }


def write_markdown(entries: List[Dict[str, Any]], output: Path) -> None:
    last_entries = entries[-20:]
    error_avg = [float(item["error_rate_avg"]) for item in entries]
    latency_p95_avg = [float(item["latency_p95_avg_ms"]) for item in entries]

    summary = [
        "# Stability Soak Trends",
        "",
        f"- Последнее обновление (UTC): {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"- Всего прогонов: {len(entries)}",
        f"- Средний error_rate (по истории): {statistics.mean(error_avg):.4f}" if error_avg else "- Средний error_rate (по истории): n/a",
        f"- Средний latency p95, ms (по истории): {statistics.mean(latency_p95_avg):.2f}" if latency_p95_avg else "- Средний latency p95, ms (по истории): n/a",
        "",
        "## Последние прогоны",
        "",
        "| timestamp_utc | status | duration_min | iterations | degraded | err_avg | err_max | p95_avg_ms | p95_max_ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for item in reversed(last_entries):
        summary.append(
            "| {timestamp_utc} | {status} | {duration_minutes} | {iterations} | {degraded_iterations} | {error_rate_avg:.4f} | {error_rate_max:.4f} | {latency_p95_avg_ms:.2f} | {latency_p95_max_ms:.2f} |".format(
                **item
            )
        )

    output.write_text("\n".join(summary) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Append soak report to persistent trend history")
    parser.add_argument("--report", required=True, help="JSON-отчёт soak run")
    parser.add_argument("--history", default="reports/stability/soak_history.jsonl")
    parser.add_argument("--summary", default="reports/stability/soak_trends.md")
    args = parser.parse_args()

    report_path = Path(args.report)
    history_path = Path(args.history)
    summary_path = Path(args.summary)

    report = load_json(report_path)
    entry = build_entry(report, source_file=str(report_path))

    entries = load_history(history_path)
    entries.append(entry)

    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in entries) + "\n", encoding="utf-8")
    write_markdown(entries=entries, output=summary_path)


if __name__ == "__main__":
    main()
