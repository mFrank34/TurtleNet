"""
TurtleNet Fleet Console Monitor
Location: tools/fleet_dashboard.py

Usage:
    python tools/fleet_dashboard.py
    python tools/fleet_dashboard.py --host 192.168.10.2 --port 8000 --interval 1.0

Requires:
    pip install rich
"""

import argparse
import json
import time
import urllib.request

from rich import box
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

DEFAULT_HOST = "192.168.10.2"
DEFAULT_PORT = 8000
DEFAULT_INTERVAL = 1.0

STATE_STYLES = {
    "RUNNING": "bold green",
    "RECOVERING": "bold yellow",
    "PAUSED": "bold cyan",
    "STOPPED": "dim white",
    "ERROR": "bold red",
    "IDLE": "dim white",
    "NO AGENT": "dim white",
}


# ── Data fetching ─────────────────────────────────────────────────────────────

def fetch_json(url: str, timeout: float = 2.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"_error": str(e)}


def fetch_fleet(host: str, port: int) -> tuple[list[dict], str | None]:
    """
    Pulls fleet state from two sources:
      1. GET /api/v1/workers/       — worker list + fuel/location from worker_store
      2. GET /workers/{id}/agent    — agent state (no /api/v1 prefix — agent router
                                      is mounted without prefix in router.py)
    """
    base_v1 = f"http://{host}:{port}/api/v1"
    base_raw = f"http://{host}:{port}"

    workers_data = fetch_json(f"{base_v1}/workers/")
    if "_error" in workers_data:
        return [], workers_data["_error"]

    workers = workers_data if isinstance(workers_data, list) else workers_data.get("workers", [])
    if not isinstance(workers, list):
        return [], f"Unexpected response shape: {str(workers_data)[:80]}"

    rows = []
    for w in workers:
        worker_id = (w.get("worker_id") or w.get("id", "?")).upper()
        fuel = w.get("fuel")
        position = w.get("location")

        # Agent router has no /api/v1 prefix — routes are /workers/{id}/agent
        agent_data = fetch_json(f"{base_raw}/workers/{worker_id}/agent")
        state = "NO AGENT"
        agent_type = "-"
        last_error = None

        if agent_data.get("ok"):
            state = (agent_data.get("state") or "UNKNOWN").upper()
            agent_type = (agent_data.get("agent_type") or "-").upper()
            extra = agent_data.get("extra", {})
            last_error = extra.get("last_error") or agent_data.get("last_error")
            if extra.get("position"):
                position = extra["position"]

        rows.append({
            "id": worker_id,
            "state": state,
            "agent_type": agent_type,
            "fuel": fuel,
            "position": position,
            "last_error": last_error,
        })

    rows.sort(key=lambda r: r["id"])
    return rows, None


# ── Rendering ─────────────────────────────────────────────────────────────────

def fmt_position(pos) -> Text:
    if not pos:
        return Text("unknown", style="dim")
    try:
        return Text(f"{round(pos['x']):>6}, {round(pos['y']):>4}, {round(pos['z']):>6}", style="dim")
    except Exception:
        return Text(str(pos), style="dim")


def fmt_error(err: str | None) -> Text:
    if not err:
        return Text("")
    err = err.replace("emergency refuel failed: no fuel found", "no fuel in inventory")
    err = err.replace("emergency refuel failed: ", "")
    return Text(err[:55], style="red")


def build_table(rows: list[dict], error: str | None, last_update: str) -> Panel:
    table = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold white",
        pad_edge=False,
        expand=True,
    )

    table.add_column("ID", style="bold white", min_width=12)
    table.add_column("AGENT", style="white", min_width=10)
    table.add_column("STATE", min_width=12)
    table.add_column("FUEL", justify="right", min_width=6)
    table.add_column("POSITION (X, Y, Z)", min_width=22)
    table.add_column("LAST ERROR", min_width=20)

    if error:
        table.add_row(Text(f"⚠  Cannot reach API: {error}", style="bold red"),
                      "", "", "", "", "")
    elif not rows:
        table.add_row(Text("No workers connected.", style="dim"), "", "", "", "", "")
    else:
        for r in rows:
            state = r["state"]
            style = STATE_STYLES.get(state, "white")
            fuel_val = r["fuel"]
            fuel_low = isinstance(fuel_val, (int, float)) and fuel_val < 160
            fuel_str = str(fuel_val) if fuel_val is not None else "?"

            table.add_row(
                r["id"],
                r["agent_type"],
                Text(state, style=style),
                Text(fuel_str, style="bold red" if fuel_low else "white"),
                fmt_position(r["position"]),
                fmt_error(r.get("last_error")),
            )

    return Panel(
        table,
        title="[bold white]🐢  TURTLENET FLEET MONITOR[/bold white]",
        subtitle=f"[dim]Updated: {last_update}   Ctrl+C to quit[/dim]",
        border_style="bright_black",
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="TurtleNet Fleet Monitor")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", default=DEFAULT_PORT, type=int)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL, type=float)
    args = parser.parse_args()

    console = Console()
    rows = []
    error = None
    last_upd = "never"

    with Live(console=console, refresh_per_second=4, screen=True) as live:
        try:
            while True:
                rows, error = fetch_fleet(args.host, args.port)
                last_upd = time.strftime("%H:%M:%S")
                live.update(build_table(rows, error, last_upd))
                time.sleep(args.interval)
        except KeyboardInterrupt:
            pass

    console.print("[dim]Monitor closed.[/dim]")


if __name__ == "__main__":
    main()
