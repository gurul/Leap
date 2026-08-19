"""Live telemetry for hunting phantom clicks (and starved screen edges).

The question this module exists to answer: when a click fires that the user
swears they did not pinch for, what did the pipeline see in the two seconds
before the trigger? Guesses about phantom clicks have been wrong before (the
2026-08 phantom-pinch diagnosis took 352 recorded select.downs to settle), so
this layer records EVERY button commit with its surrounding signal window and
lets the user tag the ones they did not intend, live, from a browser.

Three parts, one thread-safety rule:

  Telemetry        — a passive subscriber. `on_snapshot` samples the cursor
                     hand + engine state into a ring buffer; `on_intent` logs
                     events and, on select.down / grab.down, captures the ring
                     (pre-window) plus the next POST_FRAMES samples
                     (post-window) into a JSONL incident file.
  TelemetryServer  — stdlib ThreadingHTTPServer bound to 127.0.0.1 serving a
                     single-page dashboard: live pinch trace with the Schmitt
                     thresholds drawn in, event feed, cursor position (for the
                     edge-reach question), and a PHANTOM button that annotates
                     the most recent click in the log.
  wiring           — cli.py calls `on_snapshot(snap)` AFTER the engines have
                     seen the frame (so sampled Schmitt states describe this
                     frame, not the previous one) and subscribes `on_intent`
                     to the gesture engine.

The rule: this is a diagnostics layer, so it must never take down the control
loop (same contract as overlay.py). Everything called from the dispatch chain
is wrapped; a broken browser socket or a full disk costs data, never input.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from .gestures import GestureEngine, Intent, IntentEvent
from .capture import Snapshot

RING_FRAMES = 900        # ~15s at 60fps kept in memory for pre-windows
PRE_FRAMES = 120         # ~2s of context written before each button commit
POST_FRAMES = 30         # ~0.5s written after, then the incident closes
EVENT_KEEP = 200         # intent feed length for late-joining dashboards
CLIENT_QUEUE = 512       # per-browser buffer; a stalled tab drops, not blocks

# Button commits worth a full incident record. CLUTCH/POINT stay feed-only.
_CLICK_INTENTS = (Intent.SELECT_DOWN, Intent.GRAB_DOWN)


@dataclass
class _Incident:
    id: int
    intent: str
    wall: float
    pre: list = field(default_factory=list)
    post: list = field(default_factory=list)


class Telemetry:
    """Ring buffer + incident recorder. All entry points swallow exceptions."""

    def __init__(self, engine: GestureEngine, command_engine=None,
                 direct=None, source=None, hand: str = "Right",
                 pinch_on_mm: float = 0.0, pinch_off_mm: float = 0.0,
                 out_dir: Optional[Path] = None):
        self.engine = engine
        self.command_engine = command_engine
        self.direct = direct                # DirectDriver: cursor x/y for edge data
        self.source = source                # reach box, when the source has one
        self.hand = hand
        self.pinch_on_mm = pinch_on_mm
        self.pinch_off_mm = pinch_off_mm
        self.out_dir = out_dir
        self.ring: deque = deque(maxlen=RING_FRAMES)
        self.events: deque = deque(maxlen=EVENT_KEEP)
        self.clicks = 0
        self.marks = 0
        self._open: list[_Incident] = []
        self._last_settle: Optional[float] = None
        self._last_marked: Optional[int] = None
        self._clients: set[queue.Queue] = set()
        self._lock = threading.Lock()       # clients + counters; ring is
                                            # writer-single-threaded and read
                                            # via list() snapshots only
        self._path: Optional[Path] = None
        if out_dir is not None:
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
                day = time.strftime("%Y%m%d")
                self._path = out_dir / f"clicks-{day}.jsonl"
            except OSError:
                self._path = None           # no disk, still a live dashboard

    # ---- dispatch-chain entry points ------------------------------------

    def on_snapshot(self, snap: Snapshot) -> None:
        try:
            self._on_snapshot(snap)
        except Exception:
            pass                            # diagnostics never break control

    def on_intent(self, ev: IntentEvent) -> None:
        try:
            self._on_intent(ev)
        except Exception:
            pass

    def _on_snapshot(self, snap: Snapshot) -> None:
        s = self._sample(snap)
        self.ring.append(s)
        for inc in list(self._open):
            inc.post.append(s)
            if len(inc.post) >= POST_FRAMES:
                self._open.remove(inc)
                self._write({"type": "click", "id": inc.id,
                             "intent": inc.intent, "wall": inc.wall,
                             "pinch_on_mm": self.pinch_on_mm,
                             "pinch_off_mm": self.pinch_off_mm,
                             "pre": inc.pre, "post": inc.post})
        self._push({"type": "sample", **s})

    def _on_intent(self, ev: IntentEvent) -> None:
        if ev.intent is Intent.POINT_MOVE:
            # settle < 1 means "a pinch is forming, gain is reduced" — the
            # single most phantom-relevant scalar the engine computes.
            self._last_settle = ev.data.get("settle", self._last_settle)
            return
        rec = {"type": "intent", "intent": ev.intent.value,
               "wall": time.time()}
        self.events.append(rec)
        self._push(rec)
        if ev.intent in _CLICK_INTENTS:
            with self._lock:
                self.clicks += 1
                cid = self.clicks
            inc = _Incident(id=cid, intent=ev.intent.value, wall=time.time(),
                            pre=list(self.ring)[-PRE_FRAMES:])
            self._open.append(inc)
            click = {"type": "click", "id": cid, "intent": ev.intent.value,
                     "wall": inc.wall}
            self.events.append(click)
            self._push(click)

    def _sample(self, snap: Snapshot) -> dict:
        f = snap.get(self.hand)
        s = {"wall": round(time.time(), 3),
             "hand": f is not None,
             "other": snap.get("Left" if self.hand == "Right" else "Right")
                      is not None,
             "pinch": self.engine.pinch.state,
             "grab": self.engine.grab.state,
             "clutch": self.engine.clutch.state,
             "engaged": self.engine.engaged.state,
             "fingers": self.engine.fingers.value,
             "settle": self._last_settle}
        if f is not None:
            s.update(t=f.timestamp,
                     pd=round(f.pinch_distance, 2),
                     ps=round(f.pinch_strength, 3),
                     gs=round(f.grab_strength, 3),
                     ec=f.extended_count,
                     ext=sum(1 << i for i, e in enumerate(f.extended) if e),
                     ms=round(f.motion_scale, 3))
        if self.command_engine is not None:
            s["busy"] = self.command_engine.busy
            s["on"] = self.command_engine.enabled
        if self.direct is not None:
            s["cx"] = round(self.direct.x, 1)   # cursor px — edge-reach data
            s["cy"] = round(self.direct.y, 1)
        box = getattr(self.source, "_reach_now", None)
        if box:
            b = box.get(self.hand)
            if b:
                s["box"] = [round(v, 4) for v in b]
        sigs = getattr(self.source, "latest_signals", None)
        if sigs:
            sig = sigs.get(self.hand)
            span = getattr(sig, "span_img", None) if sig is not None else None
            if span:
                # Raw apparent span — the depth proxy motion_scale hides once
                # the dynamic box absorbs it. This is the rho diagnostic's
                # input (span vs position => plane tilt), so keep it raw.
                s["span"] = round(span, 4)
        return s

    # ---- dashboard entry points (HTTP threads) ---------------------------

    def mark_phantom(self, note: str = "") -> Optional[int]:
        """Tag the most recent click as unintended. Returns the click id."""
        with self._lock:
            if self.clicks == 0 or self._last_marked == self.clicks:
                return None                 # nothing new to mark; no dupes
            self._last_marked = self.clicks
            self.marks += 1
            cid = self.clicks
        rec = {"type": "mark", "click_id": cid, "note": note,
               "wall": time.time()}
        self.events.append(rec)
        self._write(rec)
        self._push(rec)
        return cid

    def state(self) -> dict:
        with self._lock:
            return {"hand": self.hand,
                    "pinch_on_mm": self.pinch_on_mm,
                    "pinch_off_mm": self.pinch_off_mm,
                    "clicks": self.clicks, "marks": self.marks,
                    "ring": list(self.ring)[-300:],
                    "events": list(self.events)[-40:],
                    "log": str(self._path) if self._path else None}

    def attach(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=CLIENT_QUEUE)
        with self._lock:
            self._clients.add(q)
        return q

    def detach(self, q: queue.Queue) -> None:
        with self._lock:
            self._clients.discard(q)

    # ---- internals --------------------------------------------------------

    def _push(self, rec: dict) -> None:
        with self._lock:
            clients = list(self._clients)
        for q in clients:
            try:
                q.put_nowait(rec)
            except queue.Full:
                pass                        # stalled tab loses frames, fine

    def _write(self, rec: dict) -> None:
        if self._path is None:
            return
        try:
            with self._path.open("a") as fh:
                fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
        except OSError:
            pass


class TelemetryServer:
    """Serves the dashboard on 127.0.0.1. `start()` returns the URL or None."""

    def __init__(self, telemetry: Telemetry, port: int = 8788):
        self.telemetry = telemetry
        self.port = port
        self._httpd: Optional[ThreadingHTTPServer] = None

    def start(self) -> Optional[str]:
        tele = self.telemetry

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):      # noqa: N802 - stdlib name
                pass                        # session log is for the session

            def _send(self, code, body, ctype="text/html; charset=utf-8"):
                data = body.encode() if isinstance(body, str) else body
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):               # noqa: N802 - stdlib name
                if self.path == "/":
                    self._send(200, _PAGE)
                elif self.path == "/state":
                    self._send(200, json.dumps(tele.state()),
                               "application/json")
                elif self.path == "/events":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    q = tele.attach()
                    try:
                        while True:
                            try:
                                rec = q.get(timeout=15)
                                payload = f"data: {json.dumps(rec)}\n\n"
                            except queue.Empty:
                                payload = ": ping\n\n"
                            self.wfile.write(payload.encode())
                            self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                    finally:
                        tele.detach(q)
                else:
                    self._send(404, "not found", "text/plain")

            def do_POST(self):              # noqa: N802 - stdlib name
                if self.path == "/mark":
                    n = int(self.headers.get("Content-Length") or 0)
                    note = self.rfile.read(n).decode(errors="replace") if n \
                        else ""
                    cid = tele.mark_phantom(note)
                    self._send(200, json.dumps({"marked": cid}),
                               "application/json")
                else:
                    self._send(404, "not found", "text/plain")

        try:
            self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port),
                                              Handler)
        except OSError:
            return None                     # port taken: dashboardless, not dead
        self.port = self._httpd.server_address[1]   # real port when asked for 0
        self._httpd.daemon_threads = True
        threading.Thread(target=self._httpd.serve_forever,
                         name="telemetry-http", daemon=True).start()
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd = None


_PAGE = """<!doctype html>
<meta charset="utf-8">
<title>leap telemetry</title>
<style>
  body{margin:0;background:#0d0f12;color:#d6d9de;font:13px/1.5 ui-monospace,Menlo,monospace}
  header{display:flex;gap:18px;align-items:baseline;padding:10px 16px;border-bottom:1px solid #23262c}
  h1{font-size:14px;margin:0;color:#f5c518}
  .stat b{color:#fff}
  #dot{color:#e0533d} #dot.live{color:#5fae6e}
  main{display:grid;grid-template-columns:2fr 1fr;gap:12px;padding:12px 16px}
  canvas{width:100%;background:#111318;border:1px solid #23262c;border-radius:4px}
  #feed{height:300px;overflow-y:auto;background:#111318;border:1px solid #23262c;border-radius:4px;padding:8px;margin:0;list-style:none}
  #feed li{padding:1px 4px} #feed .click{color:#f5c518} #feed .mark{color:#e0533d;font-weight:bold}
  #phantom{width:100%;margin-top:10px;padding:16px;font:inherit;font-size:16px;font-weight:bold;
    color:#fff;background:#a03328;border:none;border-radius:6px;cursor:pointer}
  #phantom:active{background:#e0533d}
  .hint{color:#6b7078;font-size:11px;margin-top:6px}
  #edge{margin-top:12px}
</style>
<header>
  <h1>LEAP TELEMETRY</h1>
  <span class="stat">clicks <b id="nclicks">0</b></span>
  <span class="stat">phantoms <b id="nmarks">0</b></span>
  <span class="stat" id="dot">&#9679; connecting</span>
  <span class="stat" id="log"></span>
</header>
<main>
  <div>
    <canvas id="chart" width="900" height="260"></canvas>
    <div class="hint">pinch distance (mm) &mdash; red line: arm threshold, green line: release threshold.
      Yellow bands: engine believes PINCHED. Vertical yellow: click. Vertical red: marked phantom.</div>
    <canvas id="edge" width="900" height="120"></canvas>
    <div class="hint">cursor position &mdash; x (top) and y (bottom) as a fraction of the screen.
      If pushing to the edge flatlines short of the border, that gap is the unreachable band.</div>
  </div>
  <div>
    <ul id="feed"></ul>
    <button id="phantom">PHANTOM CLICK &mdash; that one was not me (P)</button>
    <div class="hint">Tap right after a click you did not intend. It tags the most
      recent click in the on-disk log; the 2s of signals before it are already saved.</div>
  </div>
</main>
<script>
const ring=[],events=[],W=900,H=260,SPAN=20000;   // 20s window
let onMM=40,offMM=60,clicks=0,marks=0;
const $=id=>document.getElementById(id);
function feed(rec){
  const li=document.createElement("li");
  const t=new Date((rec.wall||0)*1000).toLocaleTimeString();
  if(rec.type==="click"){li.className="click";li.textContent=t+"  CLICK #"+rec.id+" ("+rec.intent+")";}
  else if(rec.type==="mark"){li.className="mark";li.textContent=t+"  PHANTOM -> click #"+rec.click_id;}
  else li.textContent=t+"  "+rec.intent;
  $("feed").prepend(li);
  while($("feed").children.length>60)$("feed").lastChild.remove();
}
function ingest(rec){
  if(rec.type==="sample"){ring.push(rec);while(ring.length>1400)ring.shift();}
  else{events.push(rec);while(events.length>200)events.shift();
       if(rec.type==="click"){clicks=rec.id;$("nclicks").textContent=clicks;}
       if(rec.type==="mark"){marks++;$("nmarks").textContent=marks;}
       feed(rec);}
}
function draw(){
  const c=$("chart").getContext("2d");c.clearRect(0,0,W,H);
  const now=Date.now(),x=w=>W-(now-w*1000)/SPAN*W,MAX=120,y=mm=>H-mm/MAX*H;
  c.strokeStyle="#e0533d";c.beginPath();c.moveTo(0,y(onMM));c.lineTo(W,y(onMM));c.stroke();
  c.strokeStyle="#5fae6e";c.beginPath();c.moveTo(0,y(offMM));c.lineTo(W,y(offMM));c.stroke();
  c.fillStyle="rgba(245,197,24,.12)";
  ring.forEach(s=>{if(s.pinch)c.fillRect(x(s.wall)-1,0,2,H);});
  c.strokeStyle="#f5c518";c.beginPath();let pen=false;
  ring.forEach(s=>{if(s.pd==null||!s.hand){pen=false;return;}
    const px=x(s.wall),py=y(Math.min(s.pd,MAX));
    pen?c.lineTo(px,py):c.moveTo(px,py);pen=true;});
  c.stroke();
  events.forEach(e=>{const px=x(e.wall);if(px<0)return;
    if(e.type==="click"){c.strokeStyle="#f5c518";c.beginPath();c.moveTo(px,0);c.lineTo(px,H);c.stroke();}
    if(e.type==="mark"){c.strokeStyle="#e0533d";c.lineWidth=2;c.beginPath();c.moveTo(px,0);c.lineTo(px,H);c.stroke();c.lineWidth=1;}});
  const e2=$("edge").getContext("2d");e2.clearRect(0,0,W,120);
  e2.strokeStyle="#23262c";[1,59,61,119].forEach(v=>{e2.beginPath();e2.moveTo(0,v);e2.lineTo(W,v);e2.stroke();});
  let sw=screen.width,sh=screen.height;
  e2.strokeStyle="#7aa2f7";e2.beginPath();pen=false;
  ring.forEach(s=>{if(s.cx==null){pen=false;return;}
    const px=x(s.wall),py=58-Math.min(s.cx/sw,1)*56;
    pen?e2.lineTo(px,py):e2.moveTo(px,py);pen=true;});
  e2.stroke();
  e2.strokeStyle="#bb9af7";e2.beginPath();pen=false;
  ring.forEach(s=>{if(s.cy==null){pen=false;return;}
    const px=x(s.wall),py=118-Math.min(s.cy/sh,1)*56;
    pen?e2.lineTo(px,py):e2.moveTo(px,py);pen=true;});
  e2.stroke();
  requestAnimationFrame(draw);
}
function mark(){fetch("/mark",{method:"POST"});}
$("phantom").onclick=mark;
addEventListener("keydown",e=>{if(e.key==="p"||e.key==="P")mark();});
fetch("/state").then(r=>r.json()).then(st=>{
  onMM=st.pinch_on_mm||onMM;offMM=st.pinch_off_mm||offMM;
  clicks=st.clicks;marks=st.marks;
  $("nclicks").textContent=clicks;$("nmarks").textContent=marks;
  if(st.log)$("log").textContent="log: "+st.log;
  st.ring.forEach(s=>ring.push({type:"sample",...s}));
  st.events.forEach(feed);
  const es=new EventSource("/events");
  es.onopen=()=>{$("dot").className="live";$("dot").innerHTML="&#9679; live";};
  es.onerror=()=>{$("dot").className="";$("dot").innerHTML="&#9679; reconnecting";};
  es.onmessage=m=>ingest(JSON.parse(m.data));
  draw();
});
</script>
"""
