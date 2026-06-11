"""
TurtleNet Fleet Monitor + Control
Location: tools/fleet_dashboard.py

Keybinds:
    Tab         Switch focus between Workers / Agents table
    ↑ / ↓       Select row
    A           Assign agent to selected worker (opens picker)
    S           Stop selected agent
    P           Pause selected agent
    R           Resume selected agent
    X           Stop ALL agents
    Ctrl+C      Quit

Requires:
    pip install rich readchar
"""

import argparse
import json
import threading
import time
import urllib.request

from rich import box
from rich.columns import Columns
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

AVAILABLE_AGENTS = ["wander"]  # extend as you add more agent types

STATE_STYLES = {
    "RUNNING": "bold green",
    "RECOVERING": "bold yellow",
    "PAUSED": "bold cyan",
    "STOPPED": "dim white",
    "ERROR": "bold red",
    "IDLE": "dim white",
    "NO AGENT": "dim",
}

FOCUS_WORKERS = 0
FOCUS_AGENTS = 1


# ── API helpers ───────────────────────────────────────────────────────────────

def fetch_json(url: str, timeout: float = 2.0) -> dict | list:
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


def fetch_workers(host: str, port: int) -> tuple[list[dict], str | None]:
    data = fetch_json(f"http://{host}:{port}/api/v1/workers/")
    if isinstance(data, dict) and "_error" in data:
        return [], data["_error"]
    workers = data if isinstance(data, list) else data.get("workers", [])
    rows = []
    for w in workers:
        rows.append({
            "id": w.get("worker_id") or w.get("id", "?"),
            "fuel": w.get("fuel"),
            "location": w.get("location"),
        })
    rows.sort(key=lambda r: r["id"])
    return rows, None


def fetch_agents(host: str, port: int) -> tuple[list[dict], str | None]:
    data = fetch_json(f"http://{host}:{port}/api/v1/agents")
    if isinstance(data, dict) and "_error" in data:
        return [], data["_error"]
    running = data.get("running", {})
    rows = []
    for worker_id, status in running.items():
        extra = status.get("extra", {})
        position = extra.get("position") or status.get("position")
        rows.append({
            "id": worker_id,
            "state": (status.get("state") or "UNKNOWN").upper(),
            "agent_type": (status.get("agent_type") or "-").upper(),
            "ticks": status.get("ticks", 0),
            "position": position,
            "last_error": status.get("last_error") or extra.get("last_error"),
        })
    rows.sort(key=lambda r: r["id"])
    return rows, None


# ── Control ───────────────────────────────────────────────────────────────────

def agent_stop(host, port, wid):
    r = api_call("DELETE", f"http://{host}:{port}/api/v1/workers/{wid}/agent")
    return "stopped" if r.get("ok") else r.get("detail") or r.get("_error", "failed")


def agent_start(host, port, wid, agent="wander"):
    r = api_call("POST", f"http://{host}:{port}/api/v1/workers/{wid}/agent",
                 {"agent": agent, "args": {}})
    return f"{agent} started" if r.get("ok") else r.get("detail") or r.get("_error", "failed")


def agent_pause(host, port, wid):
    r = api_call("POST", f"http://{host}:{port}/api/v1/workers/{wid}/agent/pause")
    return "paused" if r.get("ok") else r.get("detail") or r.get("_error", "failed")


def agent_resume(host, port, wid):
    r = api_call("POST", f"http://{host}:{port}/api/v1/workers/{wid}/agent/resume")
    return "resumed" if r.get("ok") else r.get("detail") or r.get("_error", "failed")


def agent_stop_all(host, port, agent_rows):
    ok = sum(1 for r in agent_rows if agent_stop(host, port, r["id"]) == "stopped")
    return f"stopped {ok}/{len(agent_rows)}"


# ── Rendering ─────────────────────────────────────────────────────────────────

def fmt_pos(pos) -> Text:
    if not pos:
        return Text("unknown", style="dim")
    try:
        return Text(f"{round(pos['x']):>6}, {round(pos['y']):>4}, {round(pos['z']):>6}", style="dim")
    except Exception:
        return Text(str(pos), style="dim")


def fmt_fuel(fuel) -> Text:
    if fuel is None:
        return Text("?", style="dim")
    low = isinstance(fuel, (int, float)) and fuel < 160
    return Text(str(fuel), style="bold red" if low else "white")


def fmt_error(err) -> Text:
    if not err:
        return Text("")
    err = err.replace("emergency refuel failed: ", "")
    return Text(err[:45], style="red")


def build_workers_table(rows: list[dict], selected: int, focused: bool) -> Panel:
    t = Table(box=box.SIMPLE_HEAD, show_header=True,
              header_style="bold white", pad_edge=False, expand=True)
    t.add_column("", min_width=2)
    t.add_column("ID", style="bold white", min_width=12)
    t.add_column("FUEL", justify="right", min_width=8)
    t.add_column("POSITION (X, Y, Z)", min_width=22)

    if not rows:
        t.add_row("", Text("No workers connected.", style="dim"), "", "")
    else:
        for i, r in enumerate(rows):
            is_sel = focused and i == selected
            t.add_row(
                Text("▶", style="bold cyan") if is_sel else Text(" "),
                Text(r["id"], style="bold cyan" if is_sel else "bold white"),
                fmt_fuel(r["fuel"]),
                fmt_pos(r["location"]),
            )

    border = "cyan" if focused else "bright_black"
    hint = "  [dim]A[/dim] assign agent" if focused else ""
    return Panel(t, title="[bold white]WORKERS[/bold white]" + hint,
                 border_style=border, padding=(0, 1))


def build_agents_table(rows: list[dict], selected: int, focused: bool) -> Panel:
    t = Table(box=box.SIMPLE_HEAD, show_header=True,
              header_style="bold white", pad_edge=False, expand=True)
    t.add_column("", min_width=2)
    t.add_column("ID", style="bold white", min_width=12)
    t.add_column("AGENT", style="white", min_width=10)
    t.add_column("STATE", min_width=12)
    t.add_column("TICKS", justify="right", min_width=7)
    t.add_column("POSITION (X, Y, Z)", min_width=22)
    t.add_column("LAST ERROR", min_width=20)

    if not rows:
        t.add_row("", Text("No agents running.", style="dim"), "", "", "", "", "")
    else:
        for i, r in enumerate(rows):
            is_sel = focused and i == selected
            state = r["state"]
            t.add_row(
                Text("▶", style="bold cyan") if is_sel else Text(" "),
                Text(r["id"], style="bold cyan" if is_sel else "bold white"),
                r["agent_type"],
                Text(state, style=STATE_STYLES.get(state, "white")),
                Text(str(r["ticks"]), style="dim"),
                fmt_pos(r["position"]),
                fmt_error(r.get("last_error")),
            )

    border = "cyan" if focused else "bright_black"
    hint = "  [dim]S[/dim] stop  [dim]P[/dim] pause  [dim]R[/dim] resume  [dim]X[/dim] stop all" if focused else ""
    return Panel(t, title="[bold white]AGENTS[/bold white]" + hint,
                 border_style=border, padding=(0, 1))


def build_picker(worker_id: str, agents: list[str], selected: int) -> Panel:
    t = Table(box=box.SIMPLE_HEAD, show_header=False, pad_edge=False)
    t.add_column("", min_width=2)
    t.add_column("AGENT", style="white", min_width=16)

    for i, name in enumerate(agents):
        is_sel = i == selected
        t.add_row(
            Text("▶", style="bold cyan") if is_sel else Text(" "),
            Text(name.upper(), style="bold cyan" if is_sel else "white"),
        )

    return Panel(t,
                 title=f"[bold white]Assign agent to {worker_id}[/bold white]",
                 subtitle="[dim]↑↓ select   Enter confirm   Esc cancel[/dim]",
                 border_style="cyan", padding=(0, 1))


def build_screen(
        workers, agents, worker_err, agent_err,
        focus, w_sel, a_sel,
        picking, pick_sel,
        status_msg, last_update, host, port,
) -> Panel:
    workers_panel = build_workers_table(workers, w_sel, focus == FOCUS_WORKERS)
    agents_panel = build_agents_table(agents, a_sel, focus == FOCUS_AGENTS)

    if picking and workers:
        wid = workers[w_sel]["id"]
        bottom = build_picker(wid, AVAILABLE_AGENTS, pick_sel)
    else:
        bottom = agents_panel

    status = f"[bold green]{status_msg}[/bold green]   " if status_msg else ""
    tab_hint = "[dim]Tab[/dim] switch table   [dim]Ctrl+C[/dim] quit"
    err_hint = ""
    if worker_err:
        err_hint = f"  [red]workers: {worker_err[:40]}[/red]"
    if agent_err:
        err_hint += f"  [red]agents: {agent_err[:40]}[/red]"

    return Panel(
        Columns([workers_panel, bottom], expand=True),
        title="[bold white]🐢  TURTLENET FLEET MONITOR[/bold white]"
              f"  [dim]{host}:{port}[/dim]",
        subtitle=f"{status}{tab_hint}{err_hint}\n[dim]Updated: {last_update}[/dim]",
        border_style="bright_black",
    )


# ── Input thread ──────────────────────────────────────────────────────────────

class InputHandler:
    def __init__(self):
        self.key = None
        self._lock = threading.Lock()
        if HAS_READCHAR:
            threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                k = readchar.readkey()
                with self._lock:
                    self.key = k
            except Exception:
                break

    def consume(self):
        with self._lock:
            k, self.key = self.key, None
            return k


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="TurtleNet Fleet Monitor")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", default=DEFAULT_PORT, type=int)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL, type=float)
    args = parser.parse_args()

    console = Console()
    workers = []
    agents = []
    worker_err = None
    agent_err = None
    last_upd = "never"

    focus = FOCUS_WORKERS
    w_sel = 0
    a_sel = 0
    picking = False  # agent picker open
    pick_sel = 0

    status_msg = ""
    status_ttl = 0
    next_poll = 0.0
    input_hdlr = InputHandler()

    with Live(console=console, refresh_per_second=8, screen=True) as live:
        try:
            while True:
                now = time.monotonic()

                # ── Poll API ──
                if now >= next_poll:
                    workers, worker_err = fetch_workers(args.host, args.port)
                    agents, agent_err = fetch_agents(args.host, args.port)
                    last_upd = time.strftime("%H:%M:%S")
                    next_poll = now + args.interval
                    w_sel = min(w_sel, max(0, len(workers) - 1))
                    a_sel = min(a_sel, max(0, len(agents) - 1))

                # ── Handle input ──
                key = input_hdlr.consume()
                if key:
                    UP = readchar.key.UP if HAS_READCHAR else None
                    DOWN = readchar.key.DOWN if HAS_READCHAR else None
                    ENTER = readchar.key.ENTER if HAS_READCHAR else None
                    ESC = readchar.key.ESC if HAS_READCHAR else None

                    # ── Picker mode ──
                    if picking:
                        if key == UP:
                            pick_sel = max(0, pick_sel - 1)
                        elif key == DOWN:
                            pick_sel = min(len(AVAILABLE_AGENTS) - 1, pick_sel + 1)
                        elif key == ENTER and workers:
                            wid = workers[w_sel]["id"]
                            agent_name = AVAILABLE_AGENTS[pick_sel]
                            result = agent_start(args.host, args.port, wid, agent_name)
                            status_msg = f"{wid}: {result}"
                            status_ttl = 6
                            picking = False
                            next_poll = 0
                        elif key == ESC:
                            picking = False

                    # ── Normal mode ──
                    else:
                        if key == "\t":
                            focus = FOCUS_AGENTS if focus == FOCUS_WORKERS else FOCUS_WORKERS

                        elif key == UP:
                            if focus == FOCUS_WORKERS:
                                w_sel = max(0, w_sel - 1)
                            else:
                                a_sel = max(0, a_sel - 1)

                        elif key == DOWN:
                            if focus == FOCUS_WORKERS:
                                w_sel = min(max(0, len(workers) - 1), w_sel + 1)
                            else:
                                a_sel = min(max(0, len(agents) - 1), a_sel + 1)

                        elif key in ("a", "A") and focus == FOCUS_WORKERS and workers:
                            picking = True
                            pick_sel = 0

                        elif key in ("s", "S") and focus == FOCUS_AGENTS and agents:
                            wid = agents[a_sel]["id"]
                            result = agent_stop(args.host, args.port, wid)
                            status_msg = f"{wid}: {result}"
                            status_ttl = 6
                            next_poll = 0

                        elif key in ("p", "P") and focus == FOCUS_AGENTS and agents:
                            wid = agents[a_sel]["id"]
                            result = agent_pause(args.host, args.port, wid)
                            status_msg = f"{wid}: {result}"
                            status_ttl = 6
                            next_poll = 0

                        elif key in ("r", "R") and focus == FOCUS_AGENTS and agents:
                            wid = agents[a_sel]["id"]
                            result = agent_resume(args.host, args.port, wid)
                            status_msg = f"{wid}: {result}"
                            status_ttl = 6
                            next_poll = 0

                        elif key in ("x", "X"):
                            result = agent_stop_all(args.host, args.port, agents)
                            status_msg = result
                            status_ttl = 6
                            next_poll = 0

                # Clear status
                if status_ttl > 0:
                    status_ttl -= 1
                else:
                    status_msg = ""

                live.update(build_screen(
                    workers, agents, worker_err, agent_err,
                    focus, w_sel, a_sel,
                    picking, pick_sel,
                    status_msg, last_upd, args.host, args.port,
                ))
                time.sleep(0.12)

        except KeyboardInterrupt:
            pass

    console.print("[dim]Monitor closed.[/dim]")


if __name__ == "__main__":
    main()
