#!/usr/bin/env python
"""Saga Studio — turn a manuscript into an audiobook, one chunk at a time.

    ./.venv/bin/python studio.py          # http://127.0.0.1:5010

Why it is built this way
------------------------
Every chunk's audio is content-addressed: the filename is a hash of
(text, voice, exaggeration, cfg, temperature, repetition_penalty). Edit one
line and exactly one hash changes, so exactly one chunk needs re-rendering.
Nothing else is touched, and "is this stale?" is a file-existence check rather
than bookkeeping that can drift.

The model is loaded once and held warm — a cold load is ~10s, which would make
per-line iteration unusable.

Layout:
    studio/<project>/doc.json        chunks, params, notes
    studio/<project>/source.md       the import, never modified
    studio/audio/<hash>.wav          shared cache; identical text is free
    studio/<project>/out/*.mp3       assembled book
"""
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HERE = Path(__file__).resolve().parent
# Data lives OUTSIDE the repo by default: voice clips and manuscripts are
# private, and a tool should never assume it may publish its user's material.
# Point these anywhere with SAGA_DATA / SAGA_VOICES.
ROOT = Path(os.environ.get("SAGA_DATA") or (Path.home() / ".saga-studio"))
AUDIO = ROOT / "audio"
VOICES = Path(os.environ.get("SAGA_VOICES") or (HERE / "voices"))
PORT = int(os.environ.get("PORT", "5010"))
CLAUDE = shutil.which("claude") or "/opt/homebrew/bin/claude"

ROOT.mkdir(exist_ok=True)
AUDIO.mkdir(exist_ok=True)

_model = None
_lock = threading.Lock()          # MPS: one generate() at a time
_bake = {"running": False, "done": 0, "total": 0, "project": "", "label": ""}

DEFAULTS = {"voice": "caitlyn2", "exag": 0.4, "cfg": 0.35,
            "temp": 0.7, "rep": 1.2}

# ❦ deliberately survives normalisation here: it marks a scene break, and
# assemble() gives those a longer rest. render() strips it before speaking,
# so it is a silent stage mark rather than a spoken character.
NORMALISE = [("⁓", ", "), ("—", ", "), ("…", "... "),
             ("“", '"'), ("”", '"'), ("‘", "'"), ("’", "'")]


# ── text ────────────────────────────────────────────────────────────────
def normalise(t):
    for a, b in NORMALISE:
        t = t.replace(a, b)
    return re.sub(r"[ \t]+", " ", t)


def split_chunks(text, cap=280):
    """Sentence-first, then clauses, then words. Chatterbox degrades past ~40s
    of audio per call, so no chunk may exceed the cap."""
    out = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        cur = ""
        for s in re.split(r"(?<=[.!?…])\s+", para):
            if len(cur) + len(s) + 1 <= cap:
                cur = f"{cur} {s}".strip()
            else:
                if cur:
                    out.append(cur)
                cur = s
        if cur:
            out.append(cur)
    final = []
    for c in out:
        while len(c) > cap:
            cut = c.rfind(" ", 0, cap) or cap
            final.append(c[:cut].strip())
            c = c[cut:].strip()
        if c:
            final.append(c)
    return final


def strip_markdown(md):
    md = re.sub(r"^---\n.*?\n---\n", "", md, flags=re.S)      # frontmatter
    md = re.sub(r"^#{1,6}\s*", "", md, flags=re.M)            # headings
    md = re.sub(r"\*\*\*(.*?)\*\*\*", r"\1", md)
    md = re.sub(r"\*\*(.*?)\*\*", r"\1", md)
    md = re.sub(r"(?<!\w)\*(.*?)\*(?!\w)", r"\1", md)
    md = re.sub(r"^\s*---\s*$", "❦", md, flags=re.M)          # scene break
    md = re.sub(r"`([^`]*)`", r"\1", md)
    return md


# ── voice profiles ──────────────────────────────────────────────────────
# Global, not per-project: Maddy and Anna recur across episodes, so a profile
# built once should be usable everywhere. "Default" always exists and cannot
# be deleted — every card falls back to it.
PROFILES = ROOT / "profiles.json"
BASE_PROFILE = {"voices": ["caitlyn2"], "active": 0, "exag": 0.4, "cfg": 0.35,
                "temp": 0.7, "rep": 1.2, "note": ""}


def profiles():
    if PROFILES.exists():
        p = json.loads(PROFILES.read_text())
    else:
        p = {}
    if "Default" not in p:
        p["Default"] = dict(BASE_PROFILE)
        PROFILES.write_text(json.dumps(p, indent=1))
    return p


def save_profiles(p):
    p.setdefault("Default", dict(BASE_PROFILE))
    PROFILES.write_text(json.dumps(p, indent=1))


def profile_params(name):
    p = profiles()
    prof = p.get(name) or p["Default"]
    voices = prof.get("voices") or ["caitlyn2"]
    idx = min(prof.get("active", 0), len(voices) - 1)
    return {"voice": voices[idx],
            "exag": prof.get("exag", 0.4), "cfg": prof.get("cfg", 0.35),
            "temp": prof.get("temp", 0.7), "rep": prof.get("rep", 1.2)}


def params_for(c, doc):
    """DEFAULTS <- doc defaults <- the card's profile <- per-card override."""
    return {**DEFAULTS, **doc.get("params", {}),
            **profile_params(c.get("profile", "Default")),
            **c.get("params", {})}


def chunk_hash(c, doc):
    p = params_for(c, doc)
    key = json.dumps([c["text"], p["voice"], p["exag"], p["cfg"],
                      p["temp"], p["rep"]], sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:20]


# ── projects ────────────────────────────────────────────────────────────
def pdir(name):
    return ROOT / re.sub(r"[^a-z0-9_-]+", "-", name.lower())[:60]


def load(name):
    f = pdir(name) / "doc.json"
    return json.loads(f.read_text()) if f.exists() else None


UNDO_DEPTH = 25


def snapshot(doc, label):
    """Push the current cards onto the undo stack before mutating them.

    Text only, so a stack of 25 costs almost nothing — and it covers every
    destructive action (remove, split, merge, duplicate, edits), not just the
    one that prompted it."""
    stack = doc.setdefault("_undo", [])
    stack.append({"label": label,
                  "at": time.strftime("%H:%M:%S"),
                  "chunks": json.loads(json.dumps(doc["chunks"]))})
    del stack[:-UNDO_DEPTH]


def save(doc):
    d = pdir(doc["name"])
    d.mkdir(parents=True, exist_ok=True)
    (d / "doc.json").write_text(json.dumps(doc, indent=1))


def projects():
    out = []
    for d in sorted(ROOT.iterdir()):
        f = d / "doc.json"
        if f.exists():
            doc = json.loads(f.read_text())
            chunks = doc["chunks"]
            ready = sum(1 for c in chunks if (AUDIO / f"{chunk_hash(c, doc)}.wav").exists())
            out.append({"name": doc["name"], "title": doc.get("title", doc["name"]),
                        "chunks": len(chunks), "ready": ready,
                        "words": sum(len(c["text"].split()) for c in chunks)})
    return out


def import_md(title, md):
    text = normalise(strip_markdown(md))
    chunks = [{"id": i, "text": t, "params": {}, "note": ""}
              for i, t in enumerate(split_chunks(text))]
    doc = {"name": re.sub(r"[^a-z0-9_-]+", "-", title.lower())[:60],
           "title": title, "params": {}, "chunks": chunks,
           "created": time.strftime("%Y-%m-%d %H:%M")}
    d = pdir(doc["name"])
    d.mkdir(parents=True, exist_ok=True)
    (d / "source.md").write_text(md, encoding="utf-8")
    save(doc)
    return doc


# ── audio ───────────────────────────────────────────────────────────────
def get_model():
    global _model
    if _model is None:
        from chatterbox.tts import ChatterboxTTS
        import torch
        dev = "mps" if torch.backends.mps.is_available() else "cpu"
        print(f"loading Chatterbox on {dev} …", flush=True)
        _model = ChatterboxTTS.from_pretrained(device=dev)
        print("model warm", flush=True)
    return _model


def voice_file(name):
    for ext in (".wav", ".mp3", ".flac", ".m4a"):
        p = VOICES / f"{name}{ext}"
        if p.exists():
            return p
    raise FileNotFoundError(f"no voice '{name}'")


def render(c, doc, force=False):
    """Render one chunk. With force=True the cache is bypassed and overwritten —
    the render/preview buttons always generate, so a press always means work."""
    import torchaudio as ta
    h = chunk_hash(c, doc)
    dest = AUDIO / f"{h}.wav"
    if dest.exists() and not force:
        return h, True
    p = params_for(c, doc)
    m = get_model()
    spoken = c["text"].replace("❦", " ").strip()      # scene mark: silent
    with _lock:
        wav = m.generate(spoken, audio_prompt_path=str(voice_file(p["voice"])),
                         exaggeration=p["exag"], cfg_weight=p["cfg"],
                         temperature=p["temp"], repetition_penalty=p["rep"])
    # keep the .wav extension: torchaudio picks the encoder from it, and a
    # ".part" suffix raises "Unsupported format".
    tmp = dest.with_name(dest.stem + ".tmp.wav")
    ta.save(str(tmp), wav, m.sr)
    tmp.rename(dest)                       # atomic: no half-written cache entries
    return h, False


def render_preview(c, doc, force=False, text=None):
    """Speak just the selected words.

    Chatterbox has no low-quality mode — sampling cost is per token, so the
    only real speedup is less text. Same voice and parameters as the full
    render, so what you hear is exactly what the bake will say."""
    import torchaudio as ta
    p = params_for(c, doc)
    spoken = (text if text is not None else c["text"]).replace("❦", " ").strip()
    key = json.dumps([spoken, p["voice"], p["exag"], p["cfg"], p["temp"], p["rep"], "prev"],
                     sort_keys=True)
    h = "p" + hashlib.sha256(key.encode()).hexdigest()[:19]
    dest = AUDIO / f"{h}.wav"
    if dest.exists() and not force:
        return h, True, spoken
    m = get_model()
    with _lock:
        wav = m.generate(spoken, audio_prompt_path=str(voice_file(p["voice"])),
                         exaggeration=p["exag"], cfg_weight=p["cfg"],
                         temperature=p["temp"], repetition_penalty=p["rep"])
    tmp = dest.with_name(dest.stem + ".tmp.wav")
    ta.save(str(tmp), wav, m.sr)
    tmp.rename(dest)
    return h, False, spoken


# ── job queue ───────────────────────────────────────────────────────────
# Renders run on a worker thread, so clicking away, switching documents or
# closing the tab does not stop them. One worker: MPS wants a single
# generate() at a time anyway, and a queue makes that explicit rather than
# leaving requests to pile up on a lock.
_jobs = {}
_queue = __import__("collections").deque()
_qlock = threading.Condition()
_seq = [0]


def enqueue(kind, project, cid, text=None):
    with _qlock:
        _seq[0] += 1
        jid = f"j{_seq[0]}"
        _jobs[jid] = {"id": jid, "kind": kind, "project": project, "chunk": cid,
                      "status": "queued", "text": text, "queued_at": time.time()}
        _queue.append(jid)
        _qlock.notify()
    return jid


def worker():
    while True:
        with _qlock:
            while not _queue:
                _qlock.wait()
            jid = _queue.popleft()
        j = _jobs[jid]
        j["status"] = "running"
        t0 = time.time()
        try:
            doc = load(j["project"])
            c = next(x for x in doc["chunks"] if x["id"] == j["chunk"])
            if j["kind"] == "preview":
                h, cached, spoken = render_preview(c, doc, force=True, text=j["text"])
                j.update(hash=h, chars=len(spoken), of=len(c["text"]))
            else:
                h, cached = render(c, doc, force=True)
                j.update(hash=h)
            j.update(status="done", seconds=round(time.time() - t0, 1))
        except Exception as ex:
            j.update(status="error", error=f"{type(ex).__name__}: {ex}")
        # keep the table small; finished jobs are only needed until the UI polls
        if len(_jobs) > 400:
            for k in sorted(_jobs, key=lambda k: _jobs[k]["queued_at"])[:200]:
                if _jobs[k]["status"] in ("done", "error"):
                    _jobs.pop(k, None)


threading.Thread(target=worker, daemon=True).start()


def bake(name):
    doc = load(name)
    todo = [c for c in doc["chunks"]
            if not c.get("mute") and not (AUDIO / f"{chunk_hash(c, doc)}.wav").exists()]
    _bake.update(running=True, done=0, total=len(todo), project=name, label="")
    try:
        for c in todo:
            _bake["label"] = c["text"][:60]
            render(c, doc)
            _bake["done"] += 1
    finally:
        _bake.update(running=False, label="")


def assemble(name, gap=0.35):
    """Concatenate every chunk in order. Scene breaks get a longer rest."""
    import torch, torchaudio as ta
    doc = load(name)
    m = get_model()
    pieces, missing = [], 0
    for c in doc["chunks"]:
        if c.get("mute"):                     # muted cards are simply not in the book
            continue
        f = AUDIO / f"{chunk_hash(c, doc)}.wav"
        if not f.exists():
            missing += 1
            continue
        w, sr = ta.load(str(f))
        pieces.append(w)
        rest = 1.1 if c["text"].strip().startswith("❦") else gap
        pieces.append(torch.zeros(1, int(sr * rest)))
    if not pieces:
        return None, len(doc["chunks"])
    full = torch.cat(pieces, dim=-1)
    out = pdir(name) / "out"
    out.mkdir(exist_ok=True)
    wav = out / f"{name}.wav"
    ta.save(str(wav), full, m.sr)
    mp3 = out / f"{name}.mp3"
    if shutil.which("ffmpeg"):
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-i", str(wav), "-codec:a", "libmp3lame", "-b:a", "64k",
                        "-ac", "1", str(mp3)], check=True)
        wav.unlink()
        return mp3, missing
    return wav, missing


# ── the discuss window ──────────────────────────────────────────────────
def ask_claude(project, question, chunk_ids=None):
    """Shell out to Claude Code headless, with the relevant text as context."""
    doc = load(project) if project else None
    ctx = ""
    if doc:
        sel = [c for c in doc["chunks"] if not chunk_ids or c["id"] in chunk_ids]
        sel = sel[:40]
        ctx = (f"Working on an audiobook of \"{doc['title']}\".\n"
               f"{len(doc['chunks'])} chunks total. "
               f"{'Selected' if chunk_ids else 'First'} passages:\n\n"
               + "\n\n".join(f"[chunk {c['id']}] {c['text']}" for c in sel)
               + "\n\n")
    prompt = (ctx + "Question from the author: " + question +
              "\n\nAnswer briefly and concretely. If suggesting a text change, "
              "give the exact replacement text and the chunk number.")
    try:
        r = subprocess.run([CLAUDE, "-p", prompt], capture_output=True,
                           text=True, timeout=180, cwd=str(HERE))
        return (r.stdout or r.stderr or "no reply").strip()
    except FileNotFoundError:
        return "Claude Code CLI not found — set CLAUDE or install `claude`."
    except subprocess.TimeoutExpired:
        return "Timed out after 3 minutes."


# ── http ────────────────────────────────────────────────────────────────
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            return self._send(200, (HERE / "studio_ui.html").read_bytes(), "text/html; charset=utf-8")
        if u.path == "/api/state":
            return self._send(200, {
                "projects": projects(),
                "voices": sorted(p.stem for p in VOICES.glob("*.wav")),
                "profiles": profiles(),
                "defaults": DEFAULTS, "bake": _bake,
                "model": "warm" if _model else "cold"})
        if u.path == "/api/doc":
            doc = load(q.get("name", [""])[0])
            if not doc:
                return self._send(404, {"error": "no such project"})
            for c in doc["chunks"]:
                h = chunk_hash(c, doc)
                c["hash"] = h
                c["ready"] = (AUDIO / f"{h}.wav").exists()
                c["effective"] = params_for(c, doc)
                c.setdefault("profile", "Default")
                c.setdefault("mute", False)
                c.setdefault("height", 0)
            return self._send(200, doc)
        if u.path == "/api/jobs":
            nm = q.get("name", [""])[0]
            js = [j for j in _jobs.values() if not nm or j["project"] == nm]
            js.sort(key=lambda j: j["queued_at"])
            return self._send(200, {"jobs": js[-60:],
                                    "busy": sum(1 for j in js
                                                if j["status"] in ("queued", "running"))})

        if u.path == "/api/audio":
            f = AUDIO / f"{q.get('h',[''])[0]}.wav"
            if not f.exists():
                return self._send(404, b"", "text/plain")
            return self._send(200, f.read_bytes(), "audio/wav")
        if u.path == "/api/download":
            f = pdir(q.get("name", [""])[0]) / "out" / f"{q.get('name',[''])[0]}.mp3"
            if not f.exists():
                return self._send(404, b"", "text/plain")
            return self._send(200, f.read_bytes(), "audio/mpeg")
        return self._send(404, {"error": "?"})

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        d = json.loads(self.rfile.read(n) or "{}")
        # Every mutating route needs a real project; without this a bad name
        # surfaces as an opaque 500 from subscripting None.
        if u.path not in ("/api/import", "/api/chat") and d.get("name") is not None:
            if load(d["name"]) is None:
                return self._send(404, {"error": f"no project {d['name']!r}. "
                                                 f"have: {[p['name'] for p in projects()]}"})
        try:
            if u.path == "/api/import":
                doc = import_md(d["title"], d["markdown"])
                return self._send(200, {"ok": True, "name": doc["name"],
                                        "chunks": len(doc["chunks"])})
            if u.path == "/api/chunk":
                doc = load(d["name"])
                snapshot(doc, "edit card")
                for c in doc["chunks"]:
                    if c["id"] == d["id"]:
                        if "text" in d:
                            c["text"] = normalise(d["text"])
                        if "note" in d:
                            c["note"] = d["note"]
                        if "profile" in d:
                            c["profile"] = d["profile"]
                        if "mute" in d:
                            c["mute"] = bool(d["mute"])
                        if "height" in d:          # editor height, persisted
                            c["height"] = int(d["height"])
                        if "params" in d:
                            c["params"] = {k: v for k, v in d["params"].items() if v is not None}
                save(doc)
                return self._send(200, {"ok": True})

            if u.path == "/api/duplicate":
                doc = load(d["name"])
                snapshot(doc, "duplicate")
                out = []
                for c in doc["chunks"]:
                    out.append(c)
                    if c["id"] == d["id"]:
                        out.append({**json.loads(json.dumps(c)), "note": ""})
                for i, c in enumerate(out):
                    c["id"] = i
                doc["chunks"] = out
                save(doc)
                return self._send(200, {"ok": True})

            if u.path == "/api/remove":
                doc = load(d["name"])
                snapshot(doc, "remove card")
                doc["chunks"] = [c for c in doc["chunks"] if c["id"] != d["id"]]
                for i, c in enumerate(doc["chunks"]):
                    c["id"] = i
                save(doc)
                return self._send(200, {"ok": True})

            if u.path == "/api/profile":
                p = profiles()
                nm = (d.get("profile") or "").strip()
                if not nm:
                    return self._send(400, {"error": "profile name required"})
                p[nm] = {**BASE_PROFILE, **p.get(nm, {}), **d.get("data", {})}
                save_profiles(p)
                return self._send(200, {"ok": True, "profiles": p})

            if u.path == "/api/undo":
                doc = load(d["name"])
                stack = doc.get("_undo") or []
                if not stack:
                    return self._send(200, {"ok": False, "error": "nothing to undo"})
                last = stack.pop()
                doc["chunks"] = last["chunks"]
                save(doc)
                return self._send(200, {"ok": True, "undone": last["label"],
                                        "left": len(stack)})

            if u.path == "/api/voice/upload":
                import base64
                stem = re.sub(r"[^a-z0-9_-]+", "-", Path(d["filename"]).stem.lower())[:40]
                dest = VOICES / f"{stem}.wav"
                dest.write_bytes(base64.b64decode(d["data"]))
                return self._send(200, {"ok": True, "voice": stem})

            if u.path == "/api/profile/delete":
                nm = d.get("profile")
                if nm == "Default":
                    return self._send(400, {"error": "the Default profile cannot be deleted"})
                p = profiles()
                p.pop(nm, None)
                save_profiles(p)
                # cards pointing at a deleted profile fall back to Default
                for pr in projects():
                    doc = load(pr["name"])
                    touched = False
                    for c in doc["chunks"]:
                        if c.get("profile") == nm:
                            c["profile"] = "Default"
                            touched = True
                    if touched:
                        save(doc)
                return self._send(200, {"ok": True, "profiles": p})
            if u.path == "/api/params":
                doc = load(d["name"])
                doc["params"] = d["params"]
                save(doc)
                return self._send(200, {"ok": True})
            if u.path == "/api/split":
                doc = load(d["name"])
                snapshot(doc, "split")
                out = []
                for c in doc["chunks"]:
                    if c["id"] == d["id"] and 0 < d["at"] < len(c["text"]):
                        a, b = c["text"][:d["at"]].strip(), c["text"][d["at"]:].strip()
                        out.append({**c, "text": a})
                        out.append({**c, "text": b, "note": ""})
                    else:
                        out.append(c)
                for i, c in enumerate(out):
                    c["id"] = i
                doc["chunks"] = out
                save(doc)
                return self._send(200, {"ok": True})
            if u.path == "/api/merge":
                doc = load(d["name"])
                snapshot(doc, "merge")
                out, skip = [], False
                for i, c in enumerate(doc["chunks"]):
                    if skip:
                        skip = False
                        continue
                    if c["id"] == d["id"] and i + 1 < len(doc["chunks"]):
                        nxt = doc["chunks"][i + 1]
                        out.append({**c, "text": f'{c["text"]} {nxt["text"]}'.strip()})
                        skip = True
                    else:
                        out.append(c)
                for i, c in enumerate(out):
                    c["id"] = i
                doc["chunks"] = out
                save(doc)
                return self._send(200, {"ok": True})
            if u.path == "/api/render":
                return self._send(200, {"ok": True,
                                        "job": enqueue("render", d["name"], d["id"])})
            if u.path == "/api/preview":
                sel = (d.get("text") or "").strip()
                if not sel:
                    return self._send(400, {"error": "select some text in the card first"})
                return self._send(200, {"ok": True,
                                        "job": enqueue("preview", d["name"], d["id"], sel)})

            if u.path == "/api/bake":
                if _bake["running"]:
                    return self._send(200, {"ok": False, "error": "already baking"})
                threading.Thread(target=bake, args=(d["name"],), daemon=True).start()
                return self._send(200, {"ok": True})
            if u.path == "/api/assemble":
                f, missing = assemble(d["name"])
                return self._send(200, {"ok": bool(f), "file": str(f) if f else None,
                                        "missing": missing})
            if u.path == "/api/chat":
                return self._send(200, {"reply": ask_claude(
                    d.get("name"), d["question"], d.get("chunks"))})
            if u.path == "/api/delete":
                shutil.rmtree(pdir(d["name"]), ignore_errors=True)
                return self._send(200, {"ok": True})
        except Exception as ex:
            return self._send(500, {"error": f"{type(ex).__name__}: {ex}"})
        return self._send(404, {"error": "?"})


if __name__ == "__main__":
    print(f"Saga Studio  ->  http://127.0.0.1:{PORT}")
    print("(model loads on the first render, not at boot)")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
