from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))


def _artifact_dir() -> Path:
    return Path(os.environ.get("PATCH_WORKFLOW_ARTIFACT_DIR", "outputs/patch_workflow_artifacts")).resolve()


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"raw": data}
    except Exception as exc:
        return {"_read_error": str(exc)}


def _parse_simple_daily_cron(expr: str):
    if not expr:
        return None
    parts = expr.strip().split()
    if len(parts) != 5:
        return None
    minute, hour = parts[0], parts[1]
    if not (minute.isdigit() and hour.isdigit()):
        return None
    m, h = int(minute), int(hour)
    if not (0 <= m <= 59 and 0 <= h <= 23):
        return None
    return m, h


def _previous_expected_utc(now_utc: datetime, schedule_expr: str):
    parsed = _parse_simple_daily_cron(schedule_expr)
    if not parsed:
        return None
    minute, hour = parsed
    candidate = now_utc.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate > now_utc:
        candidate -= timedelta(days=1)
    return candidate


def _format_delay(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    sign = "-" if total < 0 else ""
    total = abs(total)
    minutes = total // 60
    hours, mins = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    if days:
        return f"{sign}{days}d {hours}h {mins}m"
    if hours:
        return f"{sign}{hours}h {mins}m"
    return f"{sign}{mins}m"


def _replace_schedule_section(report: str, table: str) -> str:
    section = "## Schedule Identity\n\n" + table.strip() + "\n"
    pattern = re.compile(r"\n## Schedule Identity\n\n.*?(?=\n## |\Z)", re.S)
    if pattern.search(report):
        return pattern.sub("\n" + section, report)
    if report.strip():
        return section + "\n\n" + report
    return section + "\n"


def main() -> int:
    art = _artifact_dir()
    art.mkdir(parents=True, exist_ok=True)

    now_utc = datetime.now(timezone.utc).replace(microsecond=0)
    now_kst = now_utc.astimezone(KST)
    event_schedule = os.environ.get("GITHUB_EVENT_SCHEDULE", "") or ""
    expected_utc = _previous_expected_utc(now_utc, event_schedule)
    expected_kst = expected_utc.astimezone(KST) if expected_utc else None
    delay = (now_utc - expected_utc) if expected_utc else None

    identity_path = art / "execution_identity.json"
    identity = _read_json(identity_path)
    identity.update({
        "github_event_name": os.environ.get("GITHUB_EVENT_NAME", ""),
        "github_event_schedule": event_schedule,
        "github_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        "github_workflow": os.environ.get("GITHUB_WORKFLOW", ""),
        "github_workflow_ref": os.environ.get("GITHUB_WORKFLOW_REF", ""),
        "github_ref": os.environ.get("GITHUB_REF", ""),
        "github_sha": os.environ.get("GITHUB_SHA", identity.get("github_sha", "")),
        "actual_utc": now_utc.isoformat().replace("+00:00", "Z"),
        "actual_kst": now_kst.isoformat(),
        "runner_timezone_name": time.tzname,
        "runner_timezone_offset": datetime.now().astimezone().strftime("%z"),
        "expected_schedule_utc": expected_utc.isoformat().replace("+00:00", "Z") if expected_utc else "",
        "expected_schedule_kst": expected_kst.isoformat() if expected_kst else "",
        "schedule_delay_minutes": round(delay.total_seconds() / 60, 2) if delay else None,
        "schedule_delay_human": _format_delay(delay) if delay else "",
    })
    identity_path.write_text(json.dumps(identity, ensure_ascii=False, indent=2), encoding="utf-8")

    table = "\n".join([
        "| Key | Value |",
        "|---|---|",
        f"| event | {identity.get('github_event_name', '')} |",
        f"| github.event.schedule | {event_schedule or '-'} |",
        f"| expected UTC | {identity.get('expected_schedule_utc') or '-'} |",
        f"| expected KST | {identity.get('expected_schedule_kst') or '-'} |",
        f"| actual UTC | {identity.get('actual_utc') or '-'} |",
        f"| actual KST | {identity.get('actual_kst') or '-'} |",
        f"| delay | {identity.get('schedule_delay_human') or '-'} |",
    ])
    report_path = art / "workflow_report.md"
    report = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    report_path.write_text(_replace_schedule_section(report, table), encoding="utf-8")
    print(f"[v038] schedule identity enriched: {identity_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
