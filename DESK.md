# DESK.md — the live mixing desk

The spec for replacing premixed-stretch playback with a real-time Web Audio
mixing graph, so that every fader, mute, and the Master engage **live,
mid-word**, with no seam, no skip, no pulse — the Logic Pro model. Written
2026-08-26 at commit `61a4dd9` (the last premixed desk), with all design
decisions below already made with Caity. A fresh session should be able to
build from this document alone.

## Decisions already made (do not re-litigate)

- **Build the live desk.** No technical limitation exists; the Web Audio API
  is a node graph (sources → per-channel GainNode → Master GainNode →
  monitor GainNode → destination), which IS a mixing desk.
- **The stage rides play through the desk.** The audible skip at the current
  remix-at-the-card-seam is unacceptable and this build removes that whole
  mechanism.
- **The editor's Book Preview plays through the desk too** (her explicit
  choice over keeping it as the literal export artifact).
- **Exports keep the server's `mixdown()`** — the shipped book is still
  summed in Python. The live desk and the export must agree **by
  construction**: both consume the same timeline walk (see mix_plan).
- **The exported HTML player stays premixed** — it ships one audio file and
  has no server. Do not touch `export_player.html` playback.
- Channels remain per-story in the doc (`doc.channels`, `doc.master`), ids
  are identity ("main" is the unwritten default), names are paint, the
  default channel DISPLAYS as "Channel 1", gains 0–200%, never in any
  chunk hash. This schema is shipped and does not change.

## What exists today (anchors, at 61a4dd9)

- `studio.py`
  - `channel_gains(doc)` / `channel_gain_of(c, gains)` / `master_gain(doc)`
    just above `mixdown()` (~line 3790).
  - `mixdown(doc, gap=0.35, frm, upto, chime)` (~3800): phase 1 walks cards
    with a cursor and builds `events` of `(start, kind, w, wsr, c)` —
    reading whole wavs for durations; phase 2 places, fades, gains
    (card gain for audio kind; profile gain else; then channel gain; then
    master over the sum, before the clip). Beds: an audio card with
    `mode:"after"` advances the cursor only `after` seconds and the clip
    plays UNDER later cards. `marks` = card start times.
  - `/api/book_preview` (~7170) mixes and writes `<proj>/out/.preview.wav`;
    `/api/book_audio` serves that single file. NOTE: one preview file per
    story — concurrent mixes clobber it. The desk makes this path obsolete
    for stage + editor preview.
  - `/api/card_audio` (~5150) serves one card fx-rendered with profile ×
    channel × master gain baked (the ▶ Full button; keep as is).
  - `/api/chunk` accepts `channel`; `/api/story` accepts `channels` and
    `master` (validates, keeps main, reassigns orphaned cards on remove).
  - `fx_render(f, eff)` — plugin fx, CACHED, may change duration (tails!).
    Any duration used for planning must be measured on the **fx-rendered**
    file.
  - `_read_wav` / renders on disk are **float32 wavs (format 3)** — stdlib
    `wave` refuses them; use `soundfile` (`sf.info(path)` reads headers
    cheaply for durations).
  - `PAYLOAD` tuple (~line 75) lists shipped files — add any new file here.
  - `player.js` is served at `/player.js` (~4953) and inlined into exports
    via `/*SAGA_PLAYER*/` (~4358). A new shared `desk.js` can be served the
    same way but must NOT be inlined into exports.
- `stage_ui.html`
  - `AUDIO = new Audio()` (~191); `tick()` on `'timeupdate'` walks `MARKS`/
    `MARKI`, drives visuals/captions/`say({type:'playing'})`.
  - `story(fromId)` → `SagaPlay.walk(chunks, {playRun, ask, onEnd}, VARS,
    start)`; `playRun(tok, from, upto)` fetches `/api/book_preview` then
    plays `/api/book_audio` — **replace the body of playRun** with
    plan-fetch + engine; the walk/ask/choice structure stays untouched.
  - `REMIX` flag + seam in `tick()` + `{type:'remix'}` handling — **remove
    entirely** (the desk makes them meaningless).
  - `{type:'vol', v, mute}` message + bar slider `#vol` — becomes the
    monitor GainNode's value instead of `AUDIO.volume`.
  - `pause()`/`stop()`/`ended()`, `barDim` reads `AUDIO.paused` — the
    engine must expose equivalents (see Engine API).
- `studio_ui.html`
  - Mixer UI: `renderMixer(force)`, `chSet`, `masterSet`, `saveChannels`,
    `addChannel`, `renameChannel`, `removeChannel`, `chList/chName`;
    card header `chSelect`; profile inspector `profToChannel`. All keep
    their faces; only what is behind a change changes.
  - `MIXPEND` pulse (+ `.mixrow.pend` CSS, `mixPend`, `mixApplied`, its
    calls in `playFull`, book preview, and the stage `state` handler) —
    **remove entirely**: nothing waits any more. (Exception: see ▶ Full
    note below — no pulse there either, a fresh press fetches fresh.)
  - `{type:'remix'}` broadcasts in `saveChannels`/`masterSet` — replace
    with `{type:'mix'}` (below).
  - Book preview (`bookPlay…` ~7600): plays `/api/book_audio`, follows
    `MARKS` for card highlighting, `BOOKPLAY` sentinel, `done()` on
    pause/ended selects the card you stopped on. Rebuild on the engine,
    preserving: stop-partway-selects-that-card, end-selects-nothing,
    missing-cards chime, `from:CUR` semantics.
  - Master fader/monitor: `VOL/MUTED`, `applyVol`, `volAll` (broadcasts
    `{type:'vol'}` to the stage), `AGAIN` gain node for the asset
    inspector. `stopAllAudio` must also stop the new engine.
  - `STAGE = BroadcastChannel('saga-stage')` (~7560).

## Architecture

### 1. `/api/mix_plan` (new endpoint, GET or POST like book_preview)

Refactor `mixdown()`'s phase-1 walk into a shared helper so the plan and
the sum can never drift:

```python
def mix_events(doc, gap=0.35, frm=None, upto=None, chime=False,
               secs_of=None):
    """The cursor walk, factored out of mixdown. Returns
    (events, cursor, missing, marks) where events are
    (start, kind, path, c) tuples; path None for a chime.
    secs_of(path) supplies durations (sf.info for the plan;
    mixdown passes a reader that also caches the arrays)."""
```

`mixdown` keeps byte-identical behavior (its tests: whole-mix RMS ratios,
timeline stability under mute — see Testing). `/api/mix_plan` returns:

```json
{ "ok": true, "total": 146.37, "missing": 0,
  "marks": [{"id": 3, "at": 0.0}, …],
  "events": [
    {"id": 7, "at": 1.2, "kind": "speech", "dur": 3.41,
     "url": "/api/card_wav?name=X&id=7", "chan": "main", "gain": 1.0},
    {"id": 9, "at": 4.9, "kind": "audio", "dur": 22.0,
     "url": "/api/clip?f=foghorn", "chan": "ch2", "gain": 0.6,
     "fade": [10, 90]},
    {"id": 12, "at": 6.1, "kind": "chime", "dur": 0.45}
  ] }
```

- `gain` is the per-card STATIC factor (profile gain/100 for speech/voiced,
  card gain/100 for audio) — the client applies it on the source's own
  gain node. Channel and Master gains are NOT in the plan: the desk owns
  them live.
- `chan` is the card's channel id (default "main").
- Speech/voiced URLs must serve the **fx-rendered, gain-free** wav: new
  `/api/card_wav?name&id` = card_audio minus all gain application (fx
  still applied server-side — plugins cannot run in the browser). Same
  auth as every route.
- `frm`/`upto` exactly as book_preview (the stage's stretches between
  choice stops).
- Plan durations via `sf.info` on the fx-rendered file (fx cached, so this
  costs what the first preview already paid).

### 2. The desk graph (client, shared by stage and editor)

New shared file **`desk.js`**, served at `/desk.js` (add route + PAYLOAD
entry; `<script src="/desk.js">` in stage_ui.html and studio_ui.html; do
NOT inline into exports). It owns:

```
source (AudioBufferSourceNode)
  → srcGain (static per-card gain × fades, automation)
  → chGain[chan] (live fader)          ← {type:'mix'} messages / local UI
  → masterGain (live Master)           ← same
  → monitorGain (this machine's knob)  ← VOL/MUTED / {type:'vol'}
  → ctx.destination
```

- `setTargetAtTime(v, now, 0.03)` on every live gain change — no zipper
  noise.
- A channel id with no node yet gets one lazily; unknown ids route to
  main's node (mirrors `channel_gain_of` fallback).
- Mute = gain 0 (timeline untouched — same semantics as the server).

### 3. The engine (rolling window scheduler)

`Desk.play(plan, {onmark, onended})` returns a handle:

- `t0 = ctx.currentTime + 0.15`; ride time `t() = ctx.currentTime − t0`.
- **Window**: schedule events with `at < t() + 45`; top up every ~2s from
  the tick loop. Never decode the whole book: 2 h of 24 kHz mono float32
  is ~690 MB.
- Per event: fetch arrayBuffer → `decodeAudioData` → BufferSource →
  srcGain (apply `gain`; fades as linearRamps computed from `fade`
  percents × `dur`) → chGain → start at `t0 + at`. If decode lands late,
  `start(now, offset)` partway. Cache decoded buffers by URL (two cards
  with the same words share a wav), LRU-capped (~50).
- **Chime** events: synthesize a short tone buffer client-side (duration
  from the event; authoring-only, need not match the server's wave).
- `pause()` = `ctx.suspend()` (clock and every scheduled source freeze —
  this is the clean win over the media element); `resume()` =
  `ctx.resume()`. `stop()` = stop/disconnect all sources, mark dead so
  in-flight decodes abort.
- `playing` getter (for `barDim` etc.), `time()` for the caption clock.
- End: when `t()` ≥ `plan.total` (covers trailing silence) → `onended`.
- Drive the stage's existing `tick()` from a rAF/250 ms interval fed
  `Desk.time()` instead of `AUDIO.currentTime` (`timeupdate` no longer
  exists). MARKS/MARKI/captions/visuals logic is otherwise unchanged.

### 4. Live control flow

- Studio: `chSet`/`masterSet` — on **oninput** (every drag pixel): update
  the % label, apply to the editor's own graph immediately, and broadcast
  `{type:'mix', to:'embed', channels, master}` throttled to ~100 ms.
  On **onchange** (release): save to the server via `/api/story` as today.
  Stage: on `{type:'mix'}` apply values to its gain nodes. On plan fetch,
  seed from its own fresh `DOC`.
- Monitor: keep `{type:'vol'}` exactly as shipped; it now sets
  monitorGain instead of `AUDIO.volume` for rides (the stage's `#vol`
  slider likewise). The stage's non-ride `AUDIO` element (if any use
  remains) keeps element volume.
- Card channel reassignment mid-ride (header dropdown): already-scheduled
  sources keep their node; new schedules pick up the new channel. Accept
  this — a routing change is an authoring edit, not a fader move.

### 5. Editor Book Preview on the desk

- `bookPlay` fetches `/api/mix_plan {name, from:CUR}` (chime=true
  semantics) and runs the engine; the missing-cards chip logic keeps
  working from `plan.missing`.
- Preserve exactly: stop-partway leaves `CUR` on the card you stopped at;
  reaching the end selects nothing; `clearPlaying()`/`paintCur()` flow;
  `syncBookBtn`. Follow-the-card uses `Desk.time()` against `plan.marks`.
- `stopAllAudio()` stops the engine too (and the stage pause message stays).
- `▶ Full` (single card) keeps `/api/card_audio` with baked gains — a
  fresh press always fetches fresh, so it is correct at press time; no
  pulse, no engine needed for one card.

### 6. Voices → Channels (her feature request, build it in this pass)

A button in the Mixer panel: **"A channel per voice"** (placement: beside
"+ Add Channel"). One press:

- For every voice profile actually used by a speech/voiced card in the
  open story (in first-appearance order): ensure a channel named after the
  profile exists (create with id `v-<slug-of-profile>` to make the
  operation idempotent — re-pressing reuses them), then assign every
  card of that profile to it (skip locked, report skips).
- Cap: 24 channels total (the server clamp); if the story has more
  profiles than room, take the most-used first and say so in the status.
- Existing manual channels are left alone; cards already on a manual
  (non `v-`) channel are left alone too — the press fills in the
  unassigned, it does not bulldoze opinions.
- Status line reports: "built N channels, assigned M cards".
- This is pure client logic over the existing `/api/story` + `/api/chunk`.

### 7. Removals (do these, don't keep dead paths)

- `REMIX` flag, the seam in stage `tick()`, `{type:'remix'}` sender and
  handler.
- `MIXPEND`/`mixPend`/`mixApplied`, the `.pend` CSS, and its three clear
  hooks. The Mixer help text should stop saying "heard from the next
  play" and say the faders are live.
- Stage `playRun`'s book_preview/book_audio fetch (the endpoint itself
  stays — exports and anything else may use it).

## Invariants (the promises this build must keep)

1. **What you hear is what ships.** Live desk output must equal
   `mixdown()` output for the same doc and fader positions (modulo the
   clipper: the desk does not hard-clip; that's acceptable — Master
   below unity is the author's clip rescue, same as today).
2. **No gain in any hash.** Nothing in this build may touch `chunk_hash`.
3. **Export closure.** `.sagaproj` import/export already carries
   `doc.channels`/`doc.master` (doc.json travels wholesale) — keep it so.
4. **The exported player is untouched.**
5. **The walk is written once.** `mix_events` feeds both `mixdown` and
   the plan; no second cursor implementation anywhere.
6. **Locked cards refuse channel edits** (server already enforces).
7. Choice/ask flow, VARS, captions, visuals, follow-the-card, the
   chooser's countdown — all behaviorally unchanged.

## Testing (hard-won environment facts)

- Playground: clean-room library at `~/saga-studio-fresh`, server
  `http://127.0.0.1:5011`, launched by `~/saga-studio-fresh/start.sh`
  (voice-studio venv). **Restart it after any studio.py change** — kill
  ONLY by PID from `lsof -nP -iTCP:5011 -sTCP:LISTEN -t` after verifying
  `ps -p <pid> -o command=` shows the dev-tree studio.py. NEVER
  `pkill -f studio.py` (the pattern matches Caity's live app).
- Story `cat-story-1`: 19 cards, 18 rendered, 41 marks, one music bed,
  profiles Default/Narrator/Musti-cb/Musti-ov (cards are all on Default).
- Drive UI headless over CDP (`websockets` in system python3;
  `/json/new` needs method=PUT on current Chrome). Parse-check both HTML
  files by extracting `<script>` blocks to node --check; stage_ui.html
  needs `grep -a` (a non-UTF8 byte makes grep call it binary).
- **Headless media-element clocks freeze when muted** (element-muted or
  `--mute-audio`): no `timeupdate` ever fires. The old workaround was
  seeking + calling `tick()` by hand. The desk is BETTER here:
  `AudioContext.currentTime` advances regardless of gain values — set
  monitorGain to 0 and the whole engine is testable silently, for real.
  (An unmuted headless run PLAYS THROUGH HER SPEAKERS — avoid.)
- `mixdown` regression harness (run with the voice-studio venv python,
  `SAGA_DATA=$HOME/saga-studio-fresh`): import studio.py via
  importlib.util.spec_from_file_location; whole-mix RMS with master 50% =
  exactly 0.5000× base; channel fader 25% on one card: difference-signal
  ratio `(full−quarter)/(full−muted)` = exactly 0.7500; mute keeps marks
  identical. These must still pass after the mix_events refactor.
- Desk-vs-mixdown agreement test: render the plan through an
  OfflineAudioContext at the server sr and compare RMS against
  `mixdown()` output for the same doc (small tolerance for resampling).

## Deploy

Caity's live app serves hand-synced COPIES at
`~/git/saga-studio-electron/python/` — `cp` studio.py, studio_ui.html,
stage_ui.html, desk.js (and add desk.js to PAYLOAD) across when green.
studio.py moved → full quit+reopen; UI-only → ⌘R; the stage window needs
closing/reopening for stage_ui changes. Commit in both repos (house style:
one lyrical title `~~` body), push both.
