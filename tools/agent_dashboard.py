"""
TurtleNet Fleet Monitor + Control
Location: tools/fleet_dashboard.py

Keybinds:
    ↑ / ↓       Select turtle
    S           Stop selected agent
    A           Start wander on selected
    P           Pause selected
    R           Resume selected
    Ctrl+C      Quit

Requires:
    pip install rich
"""

import argparse
import json
import time
import urllib.error
import urllib.request

from rich import box
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

try:
    import readchar

    HAS_READCHAR = True
except ImportError:
    HAS_READCHAR = False

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


# ── API helpers ───────────────────────────────────────────────────────────────

def fetch_json(url: str, timeout: float = 2.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"_error": str(e)}


def api_call(method: str, url: str, body: dict | None = None, timeout: float = 3.0) -> dict:
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"_error": str(e)}


def fetch_fleet(host: str, port: int) -> tuple[list[dict], str | None]:
    base = f"http://{host}:{port}/api/v1"
    data = fetch_json(f"{base}/agents")
    if "_error" in data:
        return [], data["_error"]

    running = data.get("running", {})
    rows = []
    for worker_id, status in running.items():
        extra = status.get("extra", {})
        position = extra.get("position") or status.get("position")
        rows.append({
            "id": worker_id.upper(),
            "state": (status.get("state") or "UNKNOWN").upper(),
            "agent_type": (status.get("agent_type") or "-").upper(),
            "ticks": status.get("ticks", 0),
            "position": position,
            "last_error": status.get("last_error") or extra.get("last_error"),
        })

    rows.sort(key=lambda r: r["id"])
    return rows, None


# ── Control actions ───────────────────────────────────────────────────────────

def agent_stop(host: str, port: int, worker_id: str) -> str:
    r = api_call("DELETE", f"http://{host}:{port}/api/v1/workers/{worker_id}/agent")
    return "stopped" if r.get("ok") else r.get("_error") or r.get("detail", "failed")


def agent_start(host: str, port: int, worker_id: str, agent: str = "wander") -> str:
    r = api_call("POST", f"http://{host}:{port}/api/v1/workers/{worker_id}/agent",
                 {"agent": agent, "args": {}})
    return "started" if r.get("ok") else r.get("_error") or r.get("detail", "failed")


def agent_pause(host: str, port: int, worker_id: str) -> str:
    r = api_call("POST", f"http://{host}:{port}/api/v1/workers/{worker_id}/agent/pause")
    return "paused" if r.get("ok") else r.get("_error") or r.get("detail", "failed")


def agent_resume(host: str, port: int, worker_id: str) -> str:
    r = api_call("POST", f"http://{host}:{port}/api/v1/workers/{worker_id}/agent/resume")
    return "resumed" if r.get("ok") else r.get("_error") or r.get("detail", "failed")


def agent_stop_all(host: str, port: int, rows: list[dict]) -> str:
    results = [agent_stop(host, port, r["id"]) for r in rows]
    ok = sum(1 for r in results if r == "stopped")
    return f"stopped {ok}/{len(rows)}"


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
    err = err.replace("emergency refuel failed: ", "")
    return Text(err[:50], style="red")


def build_table(
        rows: list[dict],
        error: str | None,
        last_update: str,
        selected: int,
        status_msg: str,
        host: str,
        port: int,
) -> Panel:
    table = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold white",
        pad_edge=False,
        expand=True,
    )

    table.add_column("", min_width=2)  # selector
    table.add_column("ID", style="bold white", min_width=12)
    table.add_column("AGENT", style="white", min_width=10)
    table.add_column("STATE", min_width=12)
    table.add_column("TICKS", justify="right", min_width=7)
    table.add_column("POSITION (X, Y, Z)", min_width=22)
    table.add_column("LAST ERROR", min_width=20)

    if error:
        table.add_row("", Text(f"⚠  Cannot reach API: {error}", style="bold red"),
                      "", "", "", "", "")
    elif not rows:
        table.add_row("", Text("No agents running.", style="dim"), "", "", "", "", "")
    else:
        for i, r in enumerate(rows):
            is_sel = i == selected
            cursor = Text("▶", style="bold cyan") if is_sel else Text(" ")
            state = r["state"]
            style = STATE_STYLES.get(state, "white")
            id_text = Text(r["id"], style="bold cyan" if is_sel else "bold white")

            table.add_row(
                cursor,
                id_text,
                r["agent_type"],
                Text(state, style=style),
                Text(str(r["ticks"]), style="dim"),
                fmt_position(r["position"]),
                fmt_error(r.get("last_error")),
            )

    # Controls footer line
    if HAS_READCHAR:
        controls = "[cyan]↑↓[/cyan] Select  [cyan]S[/cyan] Stop  [cyan]A[/cyan] Start wander  [cyan]P[/cyan] Pause  [cyan]R[/cyan] Resume  [cyan]X[/cyan] Stop all  [cyan]Ctrl+C[/cyan] Quit"
    else:
        controls = "[dim]Install readchar for keyboard control:  pip install readchar[/dim]"

    if status_msg:
        controls = f"[bold green]{status_msg}[/bold green]   " + controls

    return Panel(
        table,
        title=f"[bold white]🐢  TURTLENET FLEET MONITOR[/bold white]  [dim]{host}:{port}[/dim]",
        subtitle=f"{controls}\n[dim]Updated: {last_update}[/dim]",
        border_style="bright_black",
    )


# ── Input thread ──────────────────────────────────────────────────────────────

import threading


class InputHandler:
    def __init__(self):
        self.key: str | None = None
        self._lock = threading.Lock()
        if HAS_READCHAR:
            t = threading.Thread(target=self._read_loop, daemon=True)
            t.start()

    def _read_loop(self):
        while True:
            try:
                k = readchar.readkey()
                with self._lock:
                    self.key = k
            except Exception:
                break

    def consume(self) -> str | None:
        with self._lock:
            k = self.key
            self.key = None
            return k


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="TurtleNet Fleet Monitor")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", default=DEFAULT_PORT, type=int)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL, type=float)
    args = parser.parse_args()

    console = Console()
    rows: list = []
    error = None
    last_upd = "never"
    selected = 0
    status_msg = ""
    status_ttl = 0  # ticks until status_msg clears
    input_hdlr = InputHandler()
    next_poll = 0.0

    if not HAS_READCHAR:
        console.print("[yellow]Tip: install readchar for keyboard control → pip install readchar[/yellow]")
        time.sleep(1.5)

    with Live(console=console, refresh_per_second=8, screen=True) as live:
        try:
            while True:
                now = time.monotonic()

                # ── Poll API ──
                if now >= next_poll:
                    rows, error = fetch_fleet(args.host, args.port)
                    last_upd = time.strftime("%H:%M:%S")
                    next_poll = now + args.interval
                    # Keep selection in bounds
                    if rows:
                        selected = min(selected, len(rows) - 1)

                # ── Handle input ──
                key = input_hdlr.consume()
                if key and rows:
                    wid = rows[selected]["id"]

                    if key == readchar.key.UP:
                        selected = max(0, selected - 1)

                    elif key == readchar.key.DOWN:
                        selected = min(len(rows) - 1, selected + 1)

                    elif key in ("s", "S"):
                        result = agent_stop(args.host, args.port, wid)
                        status_msg = f"{wid}: {result}"
                        status_ttl = 5
                        next_poll = 0  # force refresh

                    elif key in ("a", "A"):
                        result = agent_start(args.host, args.port, wid)
                        status_msg = f"{wid}: {result}"
                        status_ttl = 5
                        next_poll = 0

                    elif key in ("p", "P"):
                        result = agent_pause(args.host, args.port, wid)
                        status_msg = f"{wid}: {result}"
                        status_ttl = 5
                        next_poll = 0

                    elif key in ("r", "R"):
                        result = agent_resume(args.host, args.port, wid)
                        status_msg = f"{wid}: {result}"
                        status_ttl = 5
                        next_poll = 0

                    elif key in ("x", "X"):
                        result = agent_stop_all(args.host, args.port, rows)
                        status_msg = result
                        status_ttl = 5
                        next_poll = 0

                # Clear status message after N redraws
                if status_ttl > 0:
                    status_ttl -= 1
                else:
                    status_msg = ""

                live.update(build_table(
                    rows, error, last_upd, selected,
                    status_msg, args.host, args.port,
                ))
                time.sleep(0.12)

        except KeyboardInterrupt:
            pass

    console.print("[dim]Monitor closed.[/dim]")


if __name__ == "__main__":
    main()
