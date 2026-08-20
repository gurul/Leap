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

    def on_command(self, ev) -> None:
        """Discrete commands (the pane rect above all) into the same stream.

        The bench scores the framing gesture by comparing the rect the engine
        committed against the rect it was asked to frame, so the rect has to
        leave the process the moment it fires — reading it back out of the
        session log afterwards is not a measurement, it is archaeology.
        """
        try:
            rect = (ev.data or {}).get("rect")
            rec = {"type": "command", "command": ev.command.value,
                   "rect": [round(v, 4) for v in rect] if rect else None,
                   "wall": time.time()}
            self.events.append(rec)
            self._push(rec)
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
            if self.direct is not None:
                # WHERE the click landed, sampled at the click rather than
                # inferred from the nearest ring sample: the bench's whole
                # measurement is target-minus-landing, and a frame of cursor
                # travel is a sizeable fraction of the error being measured.
                click["cx"] = round(self.direct.x, 1)
                click["cy"] = round(self.direct.y, 1)
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
                    "screen": self.screen,
                    "mapping": self.mapping_knobs(),
                    "log": str(self._path) if self._path else None}

    @property
    def screen(self) -> Optional[list]:
        """Main-screen pixels, so the bench can put a normalized rect on it."""
        if self.direct is None:
            return None
        return [getattr(self.direct, "w", None), getattr(self.direct, "h", None)]

    def mapping_knobs(self) -> dict:
        """The hand->screen knobs the bench displays next to its scores.

        A number without the mapping that produced it cannot be compared
        against the run before it — every one of these changed in the
        2026-08-18/19 work that the accuracy complaints date from.
        """
        t = getattr(self.source, "_tuning", None)
        m = getattr(self.direct, "map", None)
        out: dict = {}
        if t is not None:
            zoom = getattr(t, "reach_zoom", None)
            out.update(reach_center=getattr(t, "reach_center", None),
                       reach_inset=getattr(t, "reach_inset", None),
                       zoom=[round(v, 2) for v in zoom] if zoom else None)
        if m is not None:
            out.update(precision_gain_min=getattr(m, "precision_gain_min", None),
                       precision_full_speed=getattr(m, "precision_full_speed",
                                                    None))
        return out

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
                elif self.path == "/bench":
                    self._send(200, _BENCH)
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


# The bench is a SEPARATE page from the dashboard on purpose: the dashboard
# answers "what did the hand do", which you read while working; the bench asks
# you to perform a known task and scores the result. Only the second one can
# answer "is this worse than it was", which is the question that matters when
# a mapping change lands. Both feed off the same /events stream.
_BENCH = """<!doctype html>
<meta charset="utf-8">
<title>leap bench</title>
<style>
  body{margin:0;background:#0d0f12;color:#d6d9de;font:13px/1.5 ui-monospace,Menlo,monospace}
  header{display:flex;gap:16px;align-items:baseline;padding:9px 16px;border-bottom:1px solid #23262c;flex-wrap:wrap}
  h1{font-size:14px;margin:0;color:#f5c518}
  .stat b{color:#fff} .stat{color:#8b9098}
  #dot{color:#e0533d} #dot.live{color:#5fae6e}
  nav{margin-left:auto;display:flex;gap:8px}
  button{font:inherit;color:#d6d9de;background:#1a1d23;border:1px solid #2e323a;border-radius:5px;padding:5px 11px;cursor:pointer}
  button.on{background:#f5c518;color:#0d0f12;border-color:#f5c518;font-weight:bold}
  #arena{position:relative;height:calc(100vh - 160px);margin:12px 16px;background:#111318;
    border:1px solid #23262c;border-radius:6px;overflow:hidden;cursor:crosshair}
  #target{position:absolute;border-radius:50%;background:#f5c518;box-shadow:0 0 0 6px rgba(245,197,24,.13)}
  #trect{position:absolute;border:2px dashed #f5c518;border-radius:3px}
  #grect{position:absolute;border:2px solid #5fae6e;border-radius:3px;background:rgba(95,174,110,.10)}
  .dot{position:absolute;width:7px;height:7px;margin:-4px 0 0 -4px;border-radius:50%;background:#e0533d}
  .dot.hit{background:#5fae6e}
  #scores{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:0 16px}
  .card{background:#111318;border:1px solid #23262c;border-radius:6px;padding:8px 11px}
  .card .k{color:#6b7078;font-size:11px;text-transform:uppercase;letter-spacing:.06em}
  .card .v{font-size:20px;color:#fff}
  .hint{color:#6b7078;font-size:11px;margin:6px 16px 0}
  #map{color:#6b7078;font-size:11px}
</style>
<header>
  <h1>LEAP BENCH</h1>
  <span class="stat" id="mode">click test</span>
  <span class="stat" id="dot">&#9679; connecting</span>
  <span class="stat" id="map"></span>
  <nav>
    <button id="bclick" class="on">CLICK test</button>
    <button id="bframe">FRAME test</button>
    <button id="breset">reset</button>
  </nav>
</header>
<div id="scores"></div>
<div id="arena"></div>
<div class="hint" id="hint"></div>
<script>
const $=id=>document.getElementById(id);
// Fixed ladder, never random: two runs are only comparable if they asked for
// the same targets. Radii end at 7px - the macOS traffic-light button, the
// target PRISM's precision layer exists to make reachable.
const TARGETS=[[.25,.30,34],[.75,.30,34],[.50,.55,24],[.20,.75,24],[.80,.72,16],
               [.50,.25,16],[.35,.60,11],[.65,.45,11],[.50,.80,7],[.28,.45,7]];
const FRAMES=[[.20,.20,.60,.55],[.45,.15,.85,.50],[.15,.45,.55,.85],[.30,.35,.70,.75]];
let mode="click",i=0,shots=[],frames=[],screenPx=null,pending=null;

function arena(){return $("arena").getBoundingClientRect();}
// Page CSS px -> screen-normalized, the space the session reports rects in.
// screenY is the OUTER window top, so the content offset is the chrome height.
function toScreenNorm(x,y){
  const sw=(screenPx&&screenPx[0])||screen.width, sh=(screenPx&&screenPx[1])||screen.height;
  const chrome=window.outerHeight-window.innerHeight;
  return [(window.screenX+x)/sw,(window.screenY+chrome+y)/sh];
}
function fmt(n,d){return n==null?"-":(+n).toFixed(d===undefined?1:d);}
function card(k,v,sub){return '<div class="card"><div class="k">'+k+'</div><div class="v">'+v+
  '</div><div class="k">'+(sub||"")+'</div></div>';}

function nextTarget(){
  const a=arena(),t=TARGETS[i%TARGETS.length];
  const x=t[0]*a.width,y=t[1]*a.height,r=t[2];
  pending={x:x,y:y,r:r,at:performance.now()};
  const el=$("target");
  el.style.cssText="position:absolute;border-radius:50%;background:#f5c518;box-shadow:0 0 0 6px rgba(245,197,24,.13);"+
    "left:"+(x-r)+"px;top:"+(y-r)+"px;width:"+(2*r)+"px;height:"+(2*r)+"px";
}
function onDown(ev){
  if(mode!=="click"||!pending)return;
  const a=arena(),x=ev.clientX-a.left,y=ev.clientY-a.top;
  const dx=x-pending.x,dy=y-pending.y,d=Math.hypot(dx,dy);
  shots.push({d:d,dx:dx,dy:dy,r:pending.r,hit:d<=pending.r,
              ms:performance.now()-pending.at});
  const dot=document.createElement("div");
  dot.className="dot"+(d<=pending.r?" hit":"");
  dot.style.left=x+"px";dot.style.top=y+"px";
  $("arena").appendChild(dot);
  i++;nextTarget();score();
}
function nextFrame(){
  const a=arena(),f=FRAMES[frames.length%FRAMES.length];
  const el=$("trect");
  el.style.cssText="position:absolute;border:2px dashed #f5c518;border-radius:3px;left:"+
    (f[0]*a.width)+"px;top:"+(f[1]*a.height)+"px;width:"+((f[2]-f[0])*a.width)+
    "px;height:"+((f[3]-f[1])*a.height)+"px";
  const p0=toScreenNorm(a.left+f[0]*a.width,a.top+f[1]*a.height);
  const p1=toScreenNorm(a.left+f[2]*a.width,a.top+f[3]*a.height);
  pending={want:[p0[0],p0[1],p1[0],p1[1]]};
}
function onPane(rect){
  if(mode!=="frame"||!pending||!rect)return;
  const w=pending.want,g=rect;
  const ix=Math.max(0,Math.min(w[2],g[2])-Math.max(w[0],g[0]));
  const iy=Math.max(0,Math.min(w[3],g[3])-Math.max(w[1],g[1]));
  const inter=ix*iy,aw=(w[2]-w[0])*(w[3]-w[1]),ag=(g[2]-g[0])*(g[3]-g[1]);
  const sw=(screenPx&&screenPx[0])||screen.width,sh=(screenPx&&screenPx[1])||screen.height;
  frames.push({iou:inter/(aw+ag-inter||1),
               dx:((g[0]+g[2])/2-(w[0]+w[2])/2)*sw,
               dy:((g[1]+g[3])/2-(w[1]+w[3])/2)*sh,
               scale:Math.sqrt(ag/(aw||1))});
  const a=arena(),chrome=window.outerHeight-window.innerHeight;
  const el=$("grect");                      // what the session actually took
  el.style.cssText="position:absolute;border:2px solid #5fae6e;border-radius:3px;"+
    "background:rgba(95,174,110,.10);left:"+(g[0]*sw-window.screenX-a.left)+"px;top:"+
    (g[1]*sh-window.screenY-chrome-a.top)+"px;width:"+((g[2]-g[0])*sw)+"px;height:"+
    ((g[3]-g[1])*sh)+"px";
  score();nextFrame();
}
function score(){
  if(mode==="click"){
    const n=shots.length,h=shots.filter(s=>s.hit).length;
    const ds=shots.map(s=>s.d).sort((a,b)=>a-b);
    const med=n?ds[Math.floor(n/2)]:null;
    const mean=n?shots.reduce((a,s)=>a+s.d,0)/n:null;
    const bx=n?shots.reduce((a,s)=>a+s.dx,0)/n:null;
    const by=n?shots.reduce((a,s)=>a+s.dy,0)/n:null;
    const small=shots.filter(s=>s.r<=11),sh_=small.filter(s=>s.hit).length;
    $("scores").innerHTML=
      card("attempts",n,"targets "+TARGETS.length+" wide")+
      card("hit rate",n?Math.round(100*h/n)+"%":"-",h+" of "+n+" inside the dot")+
      card("median miss",fmt(med)+"px","mean "+fmt(mean)+"px")+
      card("systematic bias",fmt(bx)+", "+fmt(by),"px x,y - a cluster means the MAPPING is off, not you")+
      card("small targets",small.length?Math.round(100*sh_/small.length)+"%":"-",
           "r<=11px, "+sh_+"/"+small.length);
  }else{
    const n=frames.length;
    const iou=n?frames.reduce((a,f)=>a+f.iou,0)/n:null;
    const dx=n?frames.reduce((a,f)=>a+f.dx,0)/n:null;
    const dy=n?frames.reduce((a,f)=>a+f.dy,0)/n:null;
    const sc=n?frames.reduce((a,f)=>a+f.scale,0)/n:null;
    $("scores").innerHTML=
      card("frames",n,"dashed = asked, green = captured")+
      card("overlap",n?Math.round(100*iou)+"%":"-","IoU of captured vs asked")+
      card("centre offset",fmt(dx)+", "+fmt(dy),"px - a constant offset is a SHIFTED map")+
      card("size ratio",fmt(sc,2)+"x","1.00 = right size; off means wrong ZOOM");
  }
}
function setMode(m){
  mode=m;pending=null;
  $("bclick").className=m==="click"?"on":"";$("bframe").className=m==="frame"?"on":"";
  $("mode").textContent=m+" test";
  $("arena").innerHTML=m==="click"?'<div id="target"></div>'
    :'<div id="trect"></div><div id="grect"></div>';
  $("hint").textContent=m==="click"
    ? "Point at the yellow dot and pinch. Every landing is plotted; the bias card is the one to watch - a repeatable offset in one direction is the hand->screen map, not your aim."
    : "Frame the dashed rectangle with both hands (thumb+index L on each), hold until the ring fills, release. The green box is what the session actually captured. Keep this window where it is: the bench converts page coords to screen coords through window.screenX/Y.";
  score();
  if(m==="click")nextTarget();else nextFrame();
}
$("bclick").onclick=()=>setMode("click");
$("bframe").onclick=()=>setMode("frame");
$("breset").onclick=()=>{shots=[];frames=[];i=0;setMode(mode);};
$("arena").addEventListener("pointerdown",onDown);
addEventListener("resize",()=>setMode(mode));
fetch("/state").then(r=>r.json()).then(st=>{
  screenPx=st.screen&&st.screen[0]?st.screen:null;
  const m=st.mapping||{};
  $("map").textContent="zoom "+(m.zoom?m.zoom.join("/")+"x":"-")+
    "  inset "+(m.reach_inset!=null?Math.round(m.reach_inset*100)+"%":"-")+
    "  box "+(m.reach_center||"-")+
    "  PRISM "+(m.precision_gain_min!=null?m.precision_gain_min+"x":"-");
  const es=new EventSource("/events");
  es.onopen=()=>{$("dot").className="live";$("dot").innerHTML="&#9679; live";};
  es.onerror=()=>{$("dot").className="";$("dot").innerHTML="&#9679; reconnecting";};
  es.onmessage=ev=>{const r=JSON.parse(ev.data);
    if(r.type==="command"&&r.command==="pane.new")onPane(r.rect);};
  setMode("click");
});
</script>
"""
