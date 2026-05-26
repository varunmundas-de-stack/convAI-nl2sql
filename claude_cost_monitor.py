"""
claude_cost_monitor.py — Universal Claude API Cost Monitor
Works across ANY project using Claude Code CLI or direct Anthropic API calls.

Watches TWO sources simultaneously:
  1. cost_log.jsonl  — written by cost_tracker.py (direct API calls in your code)
  2. ~/.claude/projects/**/*.jsonl — written by Claude Code CLI

Usage:
  python claude_cost_monitor.py                        # defaults: $0.50 limit, sonnet
  python claude_cost_monitor.py --limit 1.00           # custom budget
  python claude_cost_monitor.py --limit 0.25 --model opus
  python claude_cost_monitor.py --project myapp        # label for this project
  python claude_cost_monitor.py --log path/to/cost_log.jsonl  # custom log path

For VS Code auto-launch, add to .vscode/tasks.json:
  "command": "python claude_cost_monitor.py --limit 0.50 --project nl2sql"
"""

import os, sys, json, time, glob, argparse, sqlite3
from datetime import datetime, date
from pathlib import Path
from collections import defaultdict

VERSION = "1.0.0"
USAGE_DB = Path(os.getenv("USAGE_DB_PATH", Path.home() / ".claude_usage" / "usage.db"))

# ── Pricing (USD per 1M tokens) ────────────────────────────────────────────
PRICES = {
    "haiku":  {"input": 0.80,  "output": 4.00},
    "sonnet": {"input": 3.00,  "output": 15.00},
    "opus":   {"input": 15.00, "output": 75.00},
}

DEFAULT_MODEL   = "sonnet"
POLL_SECS       = 3
ALERT_COOLDOWN  = 1800  # 30 minutes between repeat alerts

# ── Claude Code CLI log locations (all platforms) ─────────────────────────
CLI_LOG_DIRS = [
    Path.home() / ".claude" / "projects",
    Path(os.environ.get("APPDATA", "~")) / "Claude" / "projects",
]

# ── Helpers ────────────────────────────────────────────────────────────────
def price_for(model: str, default: str = DEFAULT_MODEL) -> dict:
    m = model.lower()
    if "haiku"  in m: return PRICES["haiku"]
    if "opus"   in m: return PRICES["opus"]
    if "sonnet" in m: return PRICES["sonnet"]
    return PRICES.get(default, PRICES["sonnet"])

def calc_cost(model: str, inp: int, out: int, default: str = DEFAULT_MODEL) -> float:
    p = price_for(model, default)
    return (inp * p["input"] + out * p["output"]) / 1_000_000

def notify(title: str, msg: str):
    """Desktop popup with terminal fallback."""
    try:
        from plyer import notification
        notification.notify(title=title, message=msg, timeout=9)
        return
    except Exception:
        pass
    # Windows toast fallback (no plyer needed)
    try:
        import subprocess
        ps = (
            f'Add-Type -AssemblyName System.Windows.Forms;'
            f'$n=[System.Windows.Forms.NotifyIcon]::new();'
            f'$n.Icon=[System.Drawing.SystemIcons]::Information;'
            f'$n.Visible=$true;'
            f'$n.ShowBalloonTip(8000,"{title}","{msg}",[System.Windows.Forms.ToolTipIcon]::Warning);'
            f'Start-Sleep 9; $n.Visible=$false'
        )
        subprocess.Popen(["powershell", "-WindowStyle", "Hidden", "-Command", ps])
        return
    except Exception:
        pass
    # Final fallback: terminal bell + colour
    print(f"\a\033[1;31m{'='*55}\n[ALERT] {title}\n        {msg}\n{'='*55}\033[0m")


# ── SQLite daily logger ────────────────────────────────────────────────────
def db_init() -> sqlite3.Connection:
    USAGE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(USAGE_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_usage (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            logged_at    TEXT NOT NULL,
            date         TEXT NOT NULL,
            project      TEXT NOT NULL,
            caller       TEXT NOT NULL,
            model        TEXT NOT NULL,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cost_usd     REAL DEFAULT 0.0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_date    ON daily_usage(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project ON daily_usage(project)")
    conn.commit()
    return conn

def db_log_session(conn: sqlite3.Connection, tracker, project: str):
    """Write one summary row per caller for today's session."""
    today = date.today().isoformat()
    now   = datetime.utcnow().isoformat()
    rows  = []
    for caller, cost in tracker.by_caller.items():
        model = max(tracker.by_model, key=tracker.by_model.get, default="sonnet")
        rows.append((now, today, project, caller, model,
                     tracker.total_input, tracker.total_output, round(cost, 7)))
    if not rows:
        rows.append((now, today, project, "session", tracker.default_model,
                     tracker.total_input, tracker.total_output,
                     round(tracker.total_cost, 7)))
    conn.executemany("""
        INSERT INTO daily_usage
          (logged_at, date, project, caller, model, input_tokens, output_tokens, cost_usd)
        VALUES (?,?,?,?,?,?,?,?)
    """, rows)
    conn.commit()

def db_print_history(conn: sqlite3.Connection, project: str = None, days: int = 30):
    where = "WHERE date >= date('now', ?)"
    params = [f"-{days} days"]
    if project:
        where += " AND project = ?"
        params.append(project)
    rows = conn.execute(f"""
        SELECT date, project, caller, model,
               SUM(input_tokens), SUM(output_tokens), SUM(cost_usd)
        FROM daily_usage
        {where}
        GROUP BY date, project, caller
        ORDER BY date DESC, cost_usd DESC
    """, params).fetchall()

    if not rows:
        print("  No history found.")
        return

    print(f"\n  {'Date':<12} {'Project':<16} {'Caller':<22} {'Model':<10} {'In':>8} {'Out':>8} {'Cost USD':>10}")
    print("  " + "─"*92)
    for r in rows:
        print(f"  {r[0]:<12} {r[1]:<16} {r[2]:<22} {r[3]:<10} {r[4]:>8,} {r[5]:>8,} ${r[6]:>9.5f}")
    total = sum(r[6] for r in rows)
    print(f"\n  {'Total (last '+str(days)+' days)':<62} ${total:>9.5f}")

# ── Core tracker ───────────────────────────────────────────────────────────
class CostTracker:
    def __init__(self, limit: float, default_model: str, project: str):
        self.limit         = limit
        self.default_model = default_model
        self.project       = project

        # file → bytes already consumed
        self.offsets: dict[str, int] = {}

        # running totals (reset on date change)
        self._date         = date.today()
        self.total_cost    = 0.0
        self.total_input   = 0
        self.total_output  = 0
        self.total_calls   = 0

        # per-caller breakdown
        self.by_caller: dict[str, float] = defaultdict(float)
        self.by_model:  dict[str, float] = defaultdict(float)

        # alert state
        self.alerted_75    = False
        self.last_over_alert = 0.0

    def _maybe_day_reset(self, conn=None, project=""):
        today = date.today()
        if today != self._date:
            self._date         = today
            self.total_cost    = 0.0
            self.total_input   = 0
            self.total_output  = 0
            self.total_calls   = 0
            self.by_caller.clear()
            self.by_model.clear()
            if conn and self.total_calls > 0:
                db_log_session(conn, self, project)
            self.alerted_75    = False
            self.last_over_alert = 0.0

    def ingest(self, path: str, today_str: str = None):
        """Read new lines from a JSONL file since last offset."""
        offset = self.offsets.get(path, 0)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(offset)
                for line in f:
                    self._process(line.strip(), today_str)
                self.offsets[path] = f.tell()
        except OSError:
            pass

    def _process(self, line: str, today_str: str = None):
        if not line:
            return
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            return

        # Skip events not from today
        ts = ev.get("timestamp", "")
        if today_str and ts and not ts.startswith(today_str):
            return

        # Support both cost_tracker.py schema and Claude Code CLI schema
        usage = (
            ev.get("usage") or
            ev.get("message", {}).get("usage") or {}
        )
        inp = usage.get("input_tokens", 0)
        out = usage.get("output_tokens", 0)
        if not (inp or out):
            return

        model  = ev.get("model", self.default_model)
        caller = ev.get("caller") or ev.get("tool_name") or "claude-code-cli"
        cost   = ev.get("cost_usd") or calc_cost(model, inp, out, self.default_model)

        self.total_cost   += cost
        self.total_input  += inp
        self.total_output += out
        self.total_calls  += 1
        self.by_caller[caller] += cost
        self.by_model[model]   += cost

    def check_alerts(self) -> list[dict]:
        alerts = []
        now = time.time()
        pct = (self.total_cost / self.limit * 100) if self.limit else 0

        if pct >= 90 and not self.alerted_75:
            self.alerted_75 = True
            alerts.append({"level": "warn", "pct": pct})

        if pct >= 100 and (now - self.last_over_alert) > ALERT_COOLDOWN:
            self.last_over_alert = now
            alerts.append({"level": "over", "pct": pct})

        return alerts

# ── File discovery ─────────────────────────────────────────────────────────
def find_log_files(local_log: Path) -> list[str]:
    files = []
    # 1. Project-local cost_log.jsonl (from cost_tracker.py / hook)
    if local_log.exists():
        files.append(str(local_log))
    # 2. Claude Code CLI session logs
    for base in CLI_LOG_DIRS:
        try:
            if base.exists():
                files += glob.glob(str(base / "**" / "*.jsonl"), recursive=True)
        except Exception:
            pass
    return list(set(files))

# ── Status bar ────────────────────────────────────────────────────────────
def status(tracker: CostTracker, ts: str) -> str:
    pct      = tracker.total_cost / tracker.limit * 100 if tracker.limit else 0
    filled   = min(int(pct / 5), 20)
    bar      = "█" * filled + "░" * (20 - filled)
    colour   = "\033[1;31m" if pct >= 100 else "\033[1;33m" if pct >= 75 else "\033[1;32m"
    reset    = "\033[0m"

    top = (
        f"  [{ts}]  {colour}[{bar}] {pct:5.1f}%{reset}  "
        f"${tracker.total_cost:.5f} / ${tracker.limit:.2f}  "
        f"calls={tracker.total_calls}  "
        f"in={tracker.total_input:,}  out={tracker.total_output:,}"
    )

    callers = "  " + "  |  ".join(
        f"{c}: ${v:.4f}" for c, v in
        sorted(tracker.by_caller.items(), key=lambda x: -x[1])[:4]
    ) if tracker.by_caller else ""

    return top + ("\n" + callers if callers else "")

# ── Banner ─────────────────────────────────────────────────────────────────
def banner(project: str, limit: float, model: str, log: Path):
    print(f"\033[1;36m")
    print("╔══════════════════════════════════════════════════════╗")
    print(f"║  Claude Cost Monitor v{VERSION}  ·  project: {project:<14}║")
    print(f"║  Limit: ${limit:<6.2f}  Model: {model:<10}  Ctrl+C to stop   ║")
    print("╚══════════════════════════════════════════════════════╝\033[0m")
    print(f"  Local log : {log}")
    cli_active = [str(d) for d in CLI_LOG_DIRS if d.exists()]
    print(f"  CLI logs  : {cli_active or 'none found yet'}")
    print(f"  Polling   : every {POLL_SECS}s\n")

# ── Main loop ──────────────────────────────────────────────────────────────
def run(limit: float, model: str, project: str, log_path: str):
    local_log = Path(log_path)
    tracker   = CostTracker(limit, model, project)
    no_files_warned = False

    banner(project, limit, model, local_log)
    conn = db_init()

    try:
        while True:
            tracker._maybe_day_reset(conn, project)
            files = find_log_files(local_log)

            if not files and not no_files_warned:
                print("  [waiting] No log files found yet.")
                print("  Start a Claude Code session or make an API call to begin tracking.\n")
                no_files_warned = True
            if files:
                no_files_warned = False

            for f in files:
                tracker.ingest(f, date.today().isoformat())

            for alert in tracker.check_alerts():
                proj  = project
                cost  = tracker.total_cost
                pct   = alert["pct"]
                if alert["level"] == "warn":
                    notify(
                        f"⚠️ {proj} — 90% budget used",
                        f"${cost:.4f} spent ({pct:.0f}% of ${limit:.2f}) — consider /compact"
                    )
                    print(f"\n\033[1;33m  [WARN] 90% budget reached — ${cost:.4f}\033[0m")
                else:
                    notify(
                        f"🚨 {proj} — BUDGET EXCEEDED",
                        f"${cost:.4f} spent ({pct:.0f}% of ${limit:.2f}) — stop or /compact now"
                    )
                    print(f"\n\033[1;31m  [OVER] Budget exceeded — ${cost:.4f}\033[0m")

            ts = datetime.now().strftime("%H:%M:%S")
            print(f"\r\033[K{status(tracker, ts)}", end="", flush=True)

            time.sleep(POLL_SECS)

    except KeyboardInterrupt:
        if tracker.total_calls > 0:
            db_log_session(conn, tracker, project)
        print(f"\n\n\033[1;32m  Monitor stopped — session saved to DB.\033[0m")
        print(f"\n  ── Session summary ({project}) ──")
        print(f"  Total cost : ${tracker.total_cost:.5f}")
        print(f"  Total calls: {tracker.total_calls}")
        print(f"  By caller  :")
        for c, v in sorted(tracker.by_caller.items(), key=lambda x: -x[1]):
            print(f"    {c:<30} ${v:.5f}")

# ── Entry ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Universal Claude Cost Monitor")
    p.add_argument("--limit",   type=float, default=float(os.getenv("COST_LIMIT_USD", "0.50")),
                   help="Budget in USD (default 0.50)")
    p.add_argument("--model",   default=os.getenv("COST_MODEL", DEFAULT_MODEL),
                   choices=["haiku", "sonnet", "opus"],
                   help="Pricing model assumption (default: sonnet)")
    p.add_argument("--project", default=os.getenv("PROJECT_NAME", Path.cwd().name),
                   help="Project label shown in alerts (default: current folder name)")
    p.add_argument("--history", action="store_true", help="Print usage history and exit")
    p.add_argument("--days",    type=int, default=30, help="Days of history to show (default 30)")
    p.add_argument("--log",     default=os.getenv("COST_LOG_PATH", "cost_log.jsonl"),
                   help="Path to cost_log.jsonl (default: ./cost_log.jsonl)")
    args = p.parse_args()
    if args.history:
        conn = db_init()
        db_print_history(conn, args.project if args.project != Path.cwd().name else None, args.days)
        sys.exit(0)
    run(args.limit, args.model, args.project, args.log)
