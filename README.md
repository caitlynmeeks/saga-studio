# Saga Studio

Turn a manuscript into an audiobook, one chunk at a time — locally, in your own
voice, with nothing leaving your machine.

Built on [Chatterbox](https://github.com/resemble-ai/chatterbox) (Resemble AI,
MIT). Drop a markdown file in, edit the script as cards, preview a phrase, fix
what sounds wrong, and bake the book.

![local](https://img.shields.io/badge/runs-locally-7fd88f) ![no cloud](https://img.shields.io/badge/audio-never%20uploaded-7fd88f)

## Why it works this way

Every chunk's audio is **content-addressed**: the filename is a hash of
`(text, voice, exaggeration, cfg, temperature, repetition_penalty)`.

Change one line and exactly one hash changes, so exactly one chunk needs
re-rendering. "Is this stale?" is a file-existence check rather than
bookkeeping that can drift. That single decision is why fixing a mispronounced
word costs thirty seconds instead of re-rendering a five-hour book.

The model is loaded once and held warm — a cold load is ~10 seconds, which
would make per-line iteration unusable.

## Install

Needs Python 3.11+, `ffmpeg`, and a machine that can run Chatterbox (Apple
Silicon via MPS, or CUDA).

```sh
python3.11 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python studio.py          # http://127.0.0.1:5010
```

Put a **5–10 second** reference clip in `voices/<name>.wav` — that is the whole
setup for a cloned voice, no training step. Record the pauses you actually
want: prosody is copied from the reference, so a clip with the gaps edited out
produces narration that never pauses.

Only the first **6 seconds** shape cadence and the first **10** shape timbre
(Chatterbox truncates both), so put the performance at the front.

## Using it

- **Drop `.md` files** on the left. Each becomes a project; the import is
  stored untouched and never modified.
- **Cards** are editable chunks. Edit the text and the dot turns amber — that
  card, and only that card, needs re-rendering.
- **♪ Audio cards** put music or a sound effect in the stack. Pick a clip or
  import one — anything ffmpeg can read. Choose what happens next: *play it
  all, then the next card*, or *next card after N seconds* — the rest of the
  clip keeps playing **under** the narration that follows, which is how an
  intro fades out beneath the first spoken line. A two-handled fade slider
  sets ramp-in/ramp-out as percentages of the clip, and a volume slider sets
  its level under the voice. Clips are global like voices: import once, use in
  every episode.
- **◎ Voiced cards** are spoken by you, in a character's voice. Import a
  recording of yourself performing the line and Chatterbox re-speaks it as the
  card's profile — keeping your timing, your rhythm and your delivery, changing
  only the timbre. It is the card for a reading no slider will get you to: a
  laugh, an interruption, a line that has to land on a particular beat. Press
  **▶ yours** to check the take before spending a render on it.

  There are no delivery settings, because voice conversion has none — the model
  takes your recording and a voice and nothing else, so the profile's pace and
  feeling sliders do nothing here. Takes are content-addressed: importing the
  same recording twice costs nothing, and importing a second one never displaces
  the first, so a card that has already rendered keeps the performance it was
  rendered from. **⟳** re-rolls a voiced card exactly as it does a text one.
- **Per-card delivery.** The **delivery** button on a text card opens a row with
  the knobs *that card's engine actually has* — pace/feeling/steadiness/anti-stutter
  on Chatterbox, speed/length on OmniVoice — plus an engine picker, so one line
  can be spoken by the other model without a profile of its own. Overridden knobs
  turn amber; **reset** puts the card back on its profile. An override renames
  only that card's wav, so nothing else goes stale.

  Every text card shows which engine it uses in its header, with a `*` when the
  card sets it rather than the profile, and a `custom` pill when it overrides
  delivery. With two engines in one document, that stopped being guessable.

  **make profile…** in that row turns the card's current sound into a named
  profile — tune one line until the character arrives, then keep her. The card
  switches to the new profile and its overrides go away, and **nothing needs
  re-baking**: the hash is made of the resolved numbers rather than the
  profile's name, so a profile that resolves to what the card was already using
  hashes to the same wav. A per-card `length` stays on the card, since a profile
  has no field for it.
- **⤶ runs on** removes the rest before a card, so a sentence split across two
  cards is still one sentence. **Split does it for you** when the break is
  mid-sentence — which is how a phrase gets its own delivery without a pause
  appearing where you never wrote one. Splitting after a full stop leaves the
  rest alone, because there you meant it.
- **Silence cards** are a timed rest — half a second or half a minute.
- **Insert and reorder.** Hover between any two cards for the insert strip
  (+ paste · + text · + ◎ voiced · + ♪ audio · + silence), and drag any card by
  its ⠿ grip to move it. Both are undoable.
- **Copy a card, paste it anywhere.** **⧉** in a card's header copies it —
  words, profile, take, or a clip with its fades and timing — and **+ paste**
  in any insert strip drops it back, in this episode or another one. That is
  how the intro music from episode 1 gets to the top of episode 2 with the
  evening you spent tuning it still attached. The copy survives switching
  documents and closing the tab. A pasted card usually needs no rendering:
  audio is filed by a hash of the words and the voice, so the copy finds the
  wav the original already had.
- **The sidebar is three tabs** — stories, voices, clips — each with the whole
  column and its own scrollbar, sorted by name or by date. Stories sort by *last
  edited* rather than date added, because a batch import stamps twenty episodes
  with the same minute and only the edit date tells them apart.
- **The clips library** lists every music and effect clip with its length and how
  many cards use it. Play one to hear it, right-click to rename (which updates
  every card pointing at it), or **drag it into the episode** to drop an audio
  card wherever you let go. There is no delete: clips are global, undo can
  resurrect a card that names one, and an export packs whatever the cards name —
  so remove the card, not the file.
- **Voice profiles** are reusable objects: a set of voice clips plus delivery
  parameters, with a note about when to use it. Make a flat one for a character
  reading a machine log and a warm one for the same character in conversation,
  then pick per card. Profiles are global, so they work across every project.

  Because a profile's numbers are part of every hash its cards render to,
  changing one re-points every card that uses it. So edits are **held until you
  press save**, and the cost is counted while you drag: *“651 rendered cards
  would need re-baking · 4,945 cards use this profile, across 21 projects.”*
  **Save as new…** keeps the old profile intact and puts your changes in a new
  one instead.

  A profile also has a **level**, and one card can override it in the delivery
  row. It is applied when the timeline is mixed rather than when a card is
  rendered — so it is in no hash, evening out a character who reads louder than
  the rest costs nothing, and the impact line says so: *0 cards would need
  re-baking*.

  Nothing about this is destructive. Renders are content-addressed and never
  deleted, so the old audio stays on disk under its old name — **put it back**
  restores the previous settings and every card that was rendered under them
  goes green again immediately. A profile remembers its last ten settings.
- **Move cards** between profiles: in a profile's editor, move every card in the
  open episode — or just the ones on one other profile — across to it. That is
  how a story written in Default becomes a story in Gertie's voice, without
  touching what Default sounds like for everything else. Undoable with ⌘Z.
- **Two engines.** Each profile picks one:
  - **Chatterbox** — the original and the default. English, the four delivery
    controls, and seeded takes. It is also the *only* engine that can speak a
    ◎ voiced card, because it is the only one that does speech-to-speech, so
    voiced cards use it whatever the profile says.
  - **OmniVoice** — 600-odd languages and about **3× faster** (measured: 0.44×
    realtime against Chatterbox's 1.48× on the same line). This is what the
    Spanish editions are for. It has no pace/feeling/steadiness controls because
    the model has none; it has a language and a speed instead. No seed either,
    so a take still keeps its own file but re-rendering one will not reproduce it.

  The engine is part of the render hash, so the same words in the same voice
  never collide between engines — a chapter can't quietly end up half in each.
  Chatterbox is the default everywhere, so nothing already rendered goes stale
  until you deliberately move a profile across, and the impact dialog tells you
  what that costs before you do.

  OmniVoice runs in its own interpreter (`omnivoice_server.py`, started on demand
  and held warm) because it and Chatterbox pin incompatible versions of
  `transformers` and cannot share a virtualenv. Point `SAGA_OV_PYTHON` at that
  interpreter; the default is `~/git/voice-studio/.venv-omnivoice/bin/python`.
  If it is missing, the engine picker is simply disabled. Using both at once
  costs about 5 GB resident.
- **Cards fit their text.** Nothing is hidden below a fold by default; drag a
  card's corner to set a size of your own and it sticks, in either direction.
- **↗** on a document, and **open renders folder** in the footer, show the
  files in the Finder.
- **Preview selected** speaks just the words you highlight, at full quality —
  same voice, same parameters, so it is exactly what the bake will say.
  Chatterbox has no low-quality mode; the only real speedup is less text.
- **Renders run in the background.** Queue several, switch documents, close the
  tab — they keep going.
- **Find and replace** across a whole episode, with a dry run first: it lists
  every hit, and warns how many already-rendered cards a replacement would
  make stale. **⌘F** opens it, **×** or **Esc** puts it away, and it stays
  where you left it.
- **Undo** is 25 deep and covers edits, split, merge, duplicate, paste and
  remove.
- **Bake** renders everything stale. **▶ preview audiobook** mixes the whole
  book and plays it in place — the identical mix, nothing exported; press
  again to stop. **Assemble** writes that mix to an MP3: cards are placed on
  one timeline, overlapping audio is summed, and `❦` scene breaks get a
  longer rest.
- **Back up** with *export everything* — one `.sagaproj` file holding every
  document, the voice clips and profiles they need, and the rendered audio.
  Restore by dropping it back on the left. See below.
- **Discuss** shells out to the Claude Code CLI with selected cards as context,
  if you have it installed. Entirely optional.

## Your material stays yours

Voice clips and manuscripts live **outside the repo** by default:

```sh
SAGA_DATA=~/my-audiobooks SAGA_VOICES=~/my-voices ./.venv/bin/python studio.py
```

Defaults are `~/.saga-studio` for project data and `./voices` for clips. The
`.gitignore` refuses audio and manuscript directories as a second line of
defence. A ten-second reference clip is enough to clone a voice — treat those
files accordingly.

## Backups

*Export everything* under **backup** on the left writes a single `.sagaproj` —
a gzipped tar you can copy to another disk. The `⤓` on a document exports just
that one. Restore either by pressing *import…* or by dropping the file on the
same panel you drop manuscripts on.

```
manifest.json              schema, what is inside, voice checksums
profiles.json              only the profiles those documents use
projects/<name>/doc.json   cards, params, notes
projects/<name>/source.md  the untouched import
voices/<stem>.wav          only the clips those profiles can speak with
clips/<name>.wav           only the music/effects those documents place
audio/<hash>.wav           rendered chunks — optional, and nearly all the size
```

**Include rendered audio** is the whole question. With it, a 28-episode library
is a couple of hundred megabytes and restores complete. Without it, the same
backup is a few megabytes — and because chunk hashes do not depend on the
machine, restoring re-renders to *exactly* the same chunks. One is a backup of
the work; the other is a backup of the hours.

The assembled mp3 is deliberately left out: it is derived, it is large, and
*assemble* rebuilds it in seconds from the chunks that are in there.

**Nothing global is ever overwritten on import.** Voice clips, audio clips and
profiles are shared by every document, so an incoming `caitlyn2` whose bytes
differ from yours lands beside it as `caitlyn2-imported` and only the arriving
document is pointed at it — your other books cannot change how they sound because you
imported something. Renaming a voice would normally invalidate every hash that
mentions it, so hashes are recomputed on the way in and the cached audio is
re-filed to match; nothing needs re-rendering. Restoring onto the machine that
made the archive renames nothing at all.

For a document whose name is already taken, *on import, if it is already here*
decides: leave yours, replace yours, or keep both.

## Delivery parameters

| knob | what it does |
| --- | --- |
| `cfg` | pacing. Lower is slower and more deliberate |
| `exag` | emotional intensity. 0.15 is flat and machine-like; 1.0 is theatrical |
| `temp` | randomness. Lower keeps chunk 1,300 sounding like chunk 1 |
| `rep` | guards against stutters and looping syllables |

For long-form narration, lower `temp` than the default matters more than people
expect: over thousands of chunks, drift is audible as the narrator slowly
changing character.

## Roadmap

See [ROADMAP.md](ROADMAP.md) — per-card clip export, external editor hand-off,
and rendering a selection as one unit.

## Licence

MIT.
