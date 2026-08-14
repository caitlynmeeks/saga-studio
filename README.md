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
- **Voice profiles** are reusable objects: a set of voice clips plus delivery
  parameters, with a note about when to use it. Make a flat one for a character
  reading a machine log and a warm one for the same character in conversation,
  then pick per card. Profiles are global, so they work across every project.
- **Cards fit their text.** Nothing is hidden below a fold by default; drag a
  card's corner to set a size of your own and it sticks, in either direction.
- **↗** on a document, and **open renders folder** in the footer, show the
  files in the Finder.
- **Preview selected** speaks just the words you highlight, at full quality —
  same voice, same parameters, so it is exactly what the bake will say.
  Chatterbox has no low-quality mode; the only real speedup is less text.
- **Renders run in the background.** Queue several, switch documents, close the
  tab — they keep going.
- **Undo** is 25 deep and covers edits, split, merge, duplicate and remove.
- **Bake** renders everything stale. **Assemble** stitches the book into an MP3,
  giving `❦` scene breaks a longer rest.
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
audio/<hash>.wav           rendered chunks — optional, and nearly all the size
```

**Include rendered audio** is the whole question. With it, a 28-episode library
is a couple of hundred megabytes and restores complete. Without it, the same
backup is a few megabytes — and because chunk hashes do not depend on the
machine, restoring re-renders to *exactly* the same chunks. One is a backup of
the work; the other is a backup of the hours.

The assembled mp3 is deliberately left out: it is derived, it is large, and
*assemble* rebuilds it in seconds from the chunks that are in there.

**Nothing global is ever overwritten on import.** Voice clips and profiles are
shared by every document, so an incoming `caitlyn2` whose bytes differ from
yours lands beside it as `caitlyn2-imported` and only the arriving document is
pointed at it — your other books cannot change how they sound because you
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

See [ROADMAP.md](ROADMAP.md) — per-card clip export, sound-effect cards with
mixing, external editor hand-off, and rendering a selection as one unit.

## Licence

MIT.
