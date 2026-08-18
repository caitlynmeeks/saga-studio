# Voiced card

*Researched and built 2026-08-15. Import path shipped; in-browser recording deferred.*

**The idea:** a card that takes a clip you performed yourself and re-speaks it in an
assigned character's timbre — your delivery, their voice.

**Status: working.** `type: "voiced"` renders through `ChatterboxVC`, is
content-addressed like speech, bakes, mixes, assembles, copies, pastes and survives
an export/import round trip. Measured on this machine: **10.5 s** for a 6.3 s line
from cold, **4.7 s** with the TTS model already warm (VC borrows its s3gen and loads
nothing). Output is 24 kHz mono `pcm_f32le`, byte-format identical to a speech
render, and the source timing is preserved exactly.

Recording into the card from the browser is **not** built — takes are imported as
files for now. §7 has what that would need; the code is ready and only the macOS
packaging is not.

The notes below are why it is shaped the way it is.

---

## 1. What Chatterbox actually gives us

`chatterbox-tts` 0.1.7 ships three classes. We use one of them today.

| class | what it does | loaded weights |
|---|---|---|
| `ChatterboxTTS` | text → speech, timbre cloned from a reference clip | ~3.0 GB |
| **`ChatterboxVC`** | **audio → speech, timbre from a *different* clip** | **~1.0 GB** |
| `ChatterboxMultilingualTTS` | not cached, would cost ~3 GB to fetch | — |

`ChatterboxVC` is exactly the thing. The whole API is two arguments:

```python
def generate(self, audio, target_voice_path=None):
```

- `audio` — the control clip. Your performance. Resampled to 16 kHz mono internally,
  any format librosa reads.
- `target_voice_path` — the timbre donor. **This is the same voice wav the TTS path
  already passes to `audio_prompt_path`**, so character voices work as VC targets
  with no new asset type and no conversion. A voice in this system is just a bare
  wav named by its stem (`voice_file()`, `studio.py:732-737`) — `str(voice_file(name))`
  drops straight into `target_voice_path`.

Output is a `(1, N)` tensor at 24 kHz.

### Why this genuinely separates delivery from timbre

It isn't a trick or a blend — it falls out of the architecture. The pipeline is two
stages, and VC swaps the input to the second one:

```
control clip ──► S3 tokenizer ──► speech tokens ──┐
                                                   ├──► flow-matching decoder ──► HiFiGAN ──► wav
character voice ──► embed_ref ──► ref_dict ───────┘
```

The speech tokens (25 Hz, vocab 6561) carry content, timing, rhythm and delivery.
The `ref_dict` carries identity. In TTS the tokens are *invented* by the language
model from text; in VC they are *extracted from your recording*. The T3 language
model is never loaded at all.

Caveat worth internalising: S3 tokens are a semantic/acoustic code, not a pure
prosody representation. They carry some source-speaker character with them — which
is why VC preserves accent and cadence so strongly, and also why a very distinctive
source voice will tint the result. Perform in the character's register, not your own.

### What it does *not* give us

- **No knobs.** No `exaggeration`, `cfg_weight`, `temperature`, `repetition_penalty`.
  A voiced card has two inputs and nothing to tune. The card UI is correspondingly
  much simpler than a speech card — but it also means a bad result can only be fixed
  by re-performing the clip or changing the voice.
- **Target voice is truncated to the first 10 seconds.** Same as TTS, so nothing new
  — but worth knowing it already bites: `caitlyn2` is 11.14 s and `maisie-1`/`maisie-x`
  are 11.86 s, so their last second-and-a-half has never contributed to any render.
  Voices front-loaded with silence or breath convert worse.
- **No seed parameter anywhere in the package**, and the flow-matching decoder draws
  fresh noise per call. Output is stochastic. See §4 for how the existing take
  mechanism covers this.
- **No length limit and no internal chunking.** Long control clips must be split by
  us. `~/git/voice-studio/convert.py` already does this — silence-aware split into
  ≤25 s spans, then one `generate()` per span. Lift it.
- **Perth watermark applied unconditionally**, no opt-out. Same as our TTS output
  today, so nothing changes.

### Bandwidth: zero

`ChatterboxVC.from_pretrained` requests `s3gen.safetensors` and `conds.pt`. Both are
already in `~/.cache/huggingface/hub/models--ResembleAI--chatterbox`, and both are a
strict subset of what the TTS path already pulled. Nothing to download over the
solar link. Set `HF_HUB_OFFLINE=1` to skip even the etag check.

### The free-lunch detail

`ChatterboxVC.__init__(self, s3gen, device, ref_dict=None)` takes an **already
constructed** `S3Gen`. Our warm `ChatterboxTTS` in `get_model()` (`studio.py:720-729`)
holds one as `m.s3gen`.

So when the TTS model is already resident, a VC model costs **no extra VRAM and no
extra load time** — construct it directly against `m.s3gen`. And a VC-only session
(rendering nothing but voiced cards) can skip the 2 GB language model entirely.

### And a second one: skip the re-embed

`generate(audio, target_voice_path=None)` reuses whatever `ref_dict` the instance
already holds. So converting five cards against the same character costs **one**
`set_target_voice()` call, not five — hold the VC instance and only re-embed when the
resolved voice changes.

Worth flagging because the TTS path does *not* do this today: `audio_prompt_path` is
passed on every `generate()`, and chatterbox unconditionally re-runs the full
`prepare_conditionals` pipeline each time (`tts.py:219-220`) — librosa load, resample,
`embed_ref`, tokenizer pass, voice-encoder pass. A 231-card episode re-embeds the same
11-second wav 231 times. That's pre-existing headroom, not something a voiced card
creates, but it'd be a shame to copy the pattern into new code.

---

## 2. Where it plugs into the card system

Today there are three card types, dispatched by string comparison at roughly thirty
separate sites. There is no registry, no schema object, no class hierarchy.

| type | rendered? | hashed? | on the timeline? |
|---|---|---|---|
| speech (`type` absent) | yes | yes | yes |
| `audio` | no — references an uploaded file | no | yes |
| `silence` | no | no | advances cursor only |
| **`voiced`** | **yes** | **yes** | **yes** |

A voiced card is a genuinely new quadrant: **it both takes a file input and produces
rendered output.** No existing card does both, which is where the friction lives.

### Binding to a character

There is no "character" entity in the data model. The chain is:

```
card["profile"]  (string, defaults to "Default")
  → profiles.json[name]["voices"][active]   (a voice name)
    → VOICES/<name>.wav
```

A voiced card should carry `profile` exactly as a speech card does and resolve it
through the existing `profile_params()` (`studio.py:161-177`) — which means the
profile dropdown in the card header works unchanged.

But note what that resolution returns: `{voice, exag, cfg, temp, rep}`. **For VC,
four of those five are dead.** Only `voice` has any effect. That's a small wart worth
being deliberate about — either resolve just the voice, or resolve the lot and ignore
the rest, but don't let the card UI imply the "pace" and "feeling" sliders do
anything. They don't, and there is no VC equivalent.

### The precedent to copy: the audio card's upload path

The control clip can reuse the clip pipeline wholesale — it is already exactly the
right shape:

1. Hidden `<input type="file">` (`studio_ui.html:180`)
2. `POST /api/clip/upload?fn=…` with the raw File as body — **registered before the
   JSON body parse at `studio.py:1286`**, which is a real ordering constraint
3. `_clip_upload()` (`studio.py:1250-1276`) sanitises the stem to `[a-z0-9_-]`,
   streams to temp, shells to ffmpeg, transcodes to PCM wav
4. Lands in `~/.saga-studio/clips/<stem>.wav` — global, shared across projects
5. Card JSON references it **by name, never by path**

Whether control clips share the `clips/` pool or get their own `takes/` directory is
a real decision — see §5.

### The structural problem: `is_speech` conflates two things

```python
def is_speech(c):
    return c.get("type", "speech") == "speech"
```

This predicate is used at eleven sites, and it currently answers two different
questions that have never needed separating:

- *"Does this card have prose in it?"* — find/replace (`:1446`, `:1462`), split
  (`:1524`), merge (`:1544`), discuss context (`:1065`), project stats (`:342-347`).
  A voiced card should be **excluded** from all of these. Correct by default.
- *"Does this card render to a wav?"* — **bake (`:866`)**, plus `:413`, `:455`,
  `:672`, `:694`. A voiced card must be **included**. Wrong by default.

So a voiced card silently gets skipped by bake unless a second predicate is
introduced — something like `is_renderable(c)` covering speech and voiced — and all
eleven sites audited to pick the right one. **This is the single highest-risk item on
the list**, because the failure is silent: bake completes, reports success, and just
never renders your voiced cards.

### What comes for free

Because the mix dispatches `silence → audio → else`, a `voiced` type **falls through
to the speech branch** in `mixdown()` (`studio.py:957-983`) and reads
`AUDIO/<chunk_hash>.wav`. If voiced cards write into the same content-addressed pool,
mixdown needs no change at all.

That's convenient but implicit — worth a comment at the fallthrough, because it
reads like an oversight rather than a decision.

---

## 3. Caching — the one genuinely new pattern

`chunk_hash()` (`studio.py:180-189`) keys on `[text, voice, exag, cfg, temp, rep]`.
A voiced card's inputs are a **file** and a voice — and *only* those two. The four
delivery params must be **left out of the key**, or tweaking a profile's "feeling"
slider would invalidate every voiced card rendered against it and force a pointless
re-render that produces identical audio.

Options for the file half:

- **Hash the clip's bytes** (sha256 of the wav). Correct, and robust against the
  re-upload case below. Cost is a full file read per hash — clips can run to
  megabytes, and hashing happens on every `/api/doc`.
- **Hash `(name, size, mtime)`.** Cheap, but fragile.
- **Record a content hash at upload time** in a sidecar, and key on that. Cheapest at
  hash time, but adds a new mechanism and needs a backfill path for existing clips.

Why byte-hashing matters: `_clip_upload` sanitises to a stem, so **re-uploading a
different file under the same name overwrites it**. Under name-based hashing the card
would keep serving stale audio from cache with no way to notice. Under byte-hashing
it re-renders correctly.

**What was built: none of the above.** Naming the take by its own sha256 at import
time dissolves the question — the card stores a checksum, so hashing the card is
already hashing the recording's contents, at no cost on the `/api/doc` path. The
overwrite hazard goes with it: a different recording simply gets a different name.

So `chunk_hash` for a voiced card is `["voiced", perf, voice]` (+ take), and the
four delivery params are deliberately absent — verified: moving a profile's
exaggeration, cfg, temperature or repetition penalty leaves every voiced hash
unchanged, while changing the recording, the voice or the take all move it.

---

## 4. Takes give us reproducibility back

VC is stochastic and exposes no seed — but `render()` already calls
`seed_take(c.get("seed"))` before generating, which seeds torch globally. That works
identically for VC. The existing take stepper in the card UI carries over unchanged,
and take 0 keeps hashing as it does today.

This is worth having: without it, every re-render of a voiced card is a different
performance, and there's no way to get a result back once you've navigated away.

---

## 5. Decisions

### Settled

**Control clips get their own storage.** Not `VOICES/` (those are timbre donors, a
different role entirely) and not the `clips/` pool either — music, SFX and your
performance takes are different kinds of thing and shouldn't share a picker. Call it
`SAGA_DATA/takes/`.

The cost of a separate directory is four extra registration points, none of them
hard, all of them easy to forget:

- its own upload route, registered **before** the JSON body parse at `studio.py:1286`
- its own list in `/api/state` (`studio.py:1134-1143`) for the UI to read
- its own entry in the `ARC_MEMBER` archive allowlist (`studio.py:386-391`) — miss
  this and takes are **silently dropped from every backup**
- its own remap on import (`studio.py:677-679`), beside the existing audio-clip case

Also extend `clips_of()` (`studio.py:269-272`) or add a sibling, since that's what
decides which files get packed. And the never-delete rule (`studio.py:55-56`) applies
here too: undo restores card JSON only, so a take a restored card points at must
still exist.

**Record in the browser — later.** Upload-only is the wrong shape for the real
workflow (perform, listen, re-perform, and bouncing through Finder each iteration
kills it), but import is the floor you need regardless: for pre-recorded material,
for a take done properly in a DAW, and as the fallback wherever the mic isn't
available. So import shipped first, and recording is progressive enhancement on top
of it — feature-detect `navigator.mediaDevices?.getUserMedia` and show the button
only when it will work. See §7.

**Takes are content-addressed**, and stored as 16 kHz mono — exactly what VC
consumes, so nothing is lost and a backup carrying whole performances stays small.
The filename is the sha256 of the wav, which makes the §3 caching question vanish:
re-importing the same recording is free, a second take can never overwrite the
first, and a card that has rendered keeps pointing at the performance it rendered
from. It also means an import needs no name reconciliation at all — a take whose
name is already here *is* the same bytes — which is why clips need a `cmap` and
takes do not.

### Still open

1. **Chunking threshold.** `convert.py` uses ≤25 s spans split at silences. Fine for
   a line of dialogue; worth confirming against the longest control clip you'd
   realistically perform in one take.
2. **Does a voiced card carry text at all?** An optional transcript field costs
   nothing at render time and would make find/replace, discuss context and the
   assemble manifest much more useful — but then `is_speech` has to stay false while
   the card still has prose in it, which is exactly the conflation §2 warns about.
   Recommend: yes to a `note`-style transcript, no to reusing the `text` field.
3. **How long a take is worth converting in one card?** `speech_spans()` splits at
   silences into ≤25 s pieces and lays them back on the original timeline, so a long
   one works — but a voiced card is a unit on the stack, and a whole scene in one
   card is a scene you cannot reorder. Untested past ~6 s so far.

---

## 6. What was built

Nothing here was deep. The audio path is a two-argument call against a model already
in memory; the weight was breadth — and both files exist twice, since
`~/git/saga_studio/` and `~/git/saga-studio-electron/python/` are byte-identical
vendored copies. Both are in sync.

- `is_renderable()` beside `is_speech()`, and the eleven guard sites split between
  them: bake, the progress bar, export planning and import rehashing ask the new
  one; find/replace, split, merge and the discuss context keep asking the old one.
- `chunk_hash` branch, `paste_card` branch, `/api/insert` defaults, `/api/chunk`
  field clamps, `ready`/`haveperf`/`perflen` in `/api/doc`.
- `TAKES` (`SAGA_DATA/takes/`), `take_path`/`take_file`/`takes_of`,
  `POST /api/take/upload` (raw body, registered before the JSON parse) and
  `GET /api/take` for playback.
- `get_vc()`, `speech_spans()`, `render_voiced()`, `render_any()` — dispatching in
  the worker and in bake.
- `mixdown` guards its one `c["text"]` access and counts voiced as model-rate when
  picking the mix sample rate; the rest of the speech path is shared unchanged.
- Backup: takes packed unconditionally (they are sources, not derived artefacts),
  `takes/[a-z0-9]{1,40}\.wav` added to `ARC_MEMBER`, and restored with no
  reconciliation because the name is the checksum.
- Front end: `voicedCard()`, `cardHTML`/`insBar` branches, `pickPerf`/`playPerf`,
  the `perffile` input, and branches in `del`, `clipLabel`, `copyCard`, `pasteCard`,
  `assemble` and `syncCards`.

### Verified end to end

Import → attach → render → mix → assemble; dedup on re-import of the same audio
under a different filename; export/import into a fresh library leaving the card
ready without re-rendering; paste of a card whose take is absent reporting itself
unready rather than silently assembling to nothing; bake picking voiced cards up and
labelling them without touching `c["text"]`; and VC borrowing a warm TTS s3gen
(`vc.s3gen is m.s3gen`, 0.0 s to ready).

Two operational notes for whenever this gets built: the server must be launched with
voice-studio's venv python or every render fails with `ModuleNotFoundError:
torchaudio`, and job errors never reach stdout — check `curl -s
localhost:5010/api/jobs` first.

---

## 7. Recording — the code is ready, the packaging isn't

**Both hosts can record today.** The Electron window doesn't load `file://` — it loads
the Python server's own URL (`lib/backend.js:111`, `http://127.0.0.1:<port>/?k=<token>`,
via `win.loadURL(info.url)` at `main.js:122`). `127.0.0.1` is on Chromium's
potentially-trustworthy list, so both hosts are a **secure context** and
`navigator.mediaDevices` is defined in both.

Electron's permission default is **permissive**, not restrictive — it auto-approves
requests unless a handler is registered, and none is (no `setPermissionRequestHandler`
anywhere in the repo). The deny-by-default one is `setDisplayMediaRequestHandler`,
which governs screen capture, not the mic. Registering a handler is still worth doing,
but as a *narrowing* measure — grant `media` for the backend origin, deny the rest.

Nothing else blocks it: `webPreferences` (`main.js:35-40`) sets only `contextIsolation`
and `nodeIntegration`, neither of which affects capture; no CSP header is sent and no
`<meta http-equiv>` exists.

### The upload path needs zero changes

`studio_ui.html:1011-1026` POSTs the `File` as a raw body, and a `MediaRecorder` Blob
*is* a Blob — the same `fetch` works untouched. `fetch` sets `Content-Length`
automatically, satisfying `_read_body_to`'s requirement (`studio.py:1239-1241`). And
the ffmpeg call (`studio.py:1266-1267`) passes no `-f` and no input codec flags, so it
**probes the container by content** and the extension is cosmetic:

```python
r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", tmp, str(dest)], capture_output=True, text=True)
```

Local ffmpeg is 8.0.1 with `matroska,webm`, `mov,mp4,m4a`, `ogg` demuxers and `opus`,
`libopus`, `aac` decoders — so Chromium's default `audio/webm;codecs=opus` and Safari's
`audio/mp4;codecs=mp4a` both transcode cleanly to PCM wav.

### What actually needs care

- **Silent overwrite.** `stem` comes from the `fn` query param (`studio.py:1256`) with
  no collision check. A recorder that always names its blob `take.webm` overwrites the
  previous take every time, in silence. This is a second argument for the
  content-addressed take names in §5 — `<sha256>.wav` makes collisions impossible by
  construction.
- **Don't use `timeslice`.** With a timeslice, only the concatenation *from the first
  chunk* is demuxable WebM; later chunks are headerless and ffmpeg rejects them.
  Collect all chunks, upload once.
- **Pause playback before capture.** There is exactly one `<audio>` element for the
  whole app by design (`studio_ui.html:951-952`) — monitoring will bleed into the take
  otherwise.
- **Feature-detect, don't assume.** `studio.py:64` defaults `HOST=127.0.0.1`, but
  `SAGA_HOST=0.0.0.0` is advertised at `studio.py:1618`. Opened from another machine at
  `http://192.168.x.x:5010` that origin is **not** secure and `mediaDevices` is
  `undefined`. Guard on `navigator.mediaDevices?.getUserMedia` and fall back to import.
- **A level meter would be net-new.** There is no `AudioContext` anywhere in the
  codebase — playback is bare `new Audio(url)` throughout. Small
  (`createMediaStreamSource` → `AnalyserNode` → rAF) but genuinely the first Web Audio
  in the project.

### The macOS packaging debt

`npm start` works today: Electron's prebuilt binary ships
`NSMicrophoneUsageDescription`, so TCC prompts and attributes it to "Electron".

A **packaged** build is a different story, and it has never been exercised —
`electron-builder` isn't installed, there is no `dist/`, and no `.plist` exists in the
repo. `package.json:29-36` sets only category, target and icon. Consequences:

1. `hardenedRuntime` defaults to **true**.
2. The stock entitlements template carries only `allow-jit`,
   `allow-unsigned-executable-memory` and `disable-library-validation` — **not**
   `com.apple.security.device.audio-input`.
3. Under hardened runtime with no audio-input entitlement, **the mic yields silence
   rather than an error** — a take that records, uploads, transcodes and plays back
   empty. That's the worst possible failure mode for this feature.
4. Signing is unconfigured, so TCC identity is unstable and a granted permission can
   evaporate between builds.

To ship a `.dmg` with recording you'd need: `electron-builder` installed, an
entitlements plist with `com.apple.security.device.audio-input` wired via
`build.mac.entitlements`, a `mac.extendInfo.NSMicrophoneUsageDescription` string
(Electron's generic one reads badly in the prompt), and a signing identity.

**None of that blocks starting.** It's pre-existing debt you'd pay before shipping a
packaged build regardless of this feature. Build browser-first; treat packaging as a
separable second task.
