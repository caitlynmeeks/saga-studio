# Saga Studio — roadmap

Requested 2026-08-13. Core (import → chunk → profile → preview → render →
bake → assemble → undo) is built and working; everything below is deferred so
the core stays solid first.

Ordered by how much architecture each one disturbs.

---

## 1. Export / import a project as one file

**What:** one button out, one button in. A single portable file containing
`doc.json`, `source.md`, every voice clip the project references, the profiles
it uses, and the rendered audio.

**Shape:** gzipped tar with a distinct extension — `.sagaproj`. Tar because it
is already everywhere, streams, and survives being emailed.

```
manifest.json      schema version, title, created, checksums
doc.json           cards, profiles-in-use, params
source.md          the untouched import
voices/*.wav       only clips actually referenced
audio/*.wav        rendered chunks (optional: --with-audio, it is the bulk)
```

**Watch out:** audio is by far the largest part — a 5-hour book is ~1.5 GB of
chunk WAVs. Offer *with* and *without* audio; without it, the importing side
re-renders from the same hashes and lands in the same place.

**On import:** voice-name collisions are the real hazard. If `caitlyn2.wav`
already exists and differs by checksum, import as `caitlyn2-imported.wav` and
repoint that project's profiles at it. Never silently overwrite a voice — it
would change how every other project sounds.

## 2. Export clip

**What:** a button per card to export just that chunk's audio.

Trivial next to the rest: the WAV already exists in the cache. Needs a Save
dialog and a sensible filename (`<project>-c07-<first-few-words>.wav`), plus
a format choice — WAV for editing, MP3 for sending to someone.

## 3. Open in your audio editor

**What:** a preference for an external editor (Logic Pro, Audacity, Ferrite),
and an "open in…" button on a card and on the assembled book.

Implementation is `open -a "Logic Pro" <file>` on macOS. Store the choice in
`studio/settings.json`. Populate the menu from `/Applications` rather than
making her type a path.

Worth pairing with **export stems** — one file per card, numbered in order —
since that is what an editor actually wants for a real mix.

## 4. Sound-effect cards  ← the big one

**What:** import an audio clip as a new kind of card, with two behaviours:

- **play to completion** — sequential; narration waits for it.
- **render beneath** — the effect plays *under* the following narration.

**Why this is the largest change:** the document is currently a *list* that
concatenates. "Underneath" makes it a *timeline* with overlapping regions, and
assemble() stops being concatenation and becomes a mix. That is a real model
change, so it deserves its own pass rather than being bolted on.

Suggested card fields:

```
kind: "sfx"
file: studio/<project>/sfx/rain.wav
mode: "sequential" | "under"
under_span: 3          # how many following cards it plays beneath
gain_db: -12           # effects almost always want to sit well below voice
fade_in / fade_out: 0.5
loop: false            # for beds shorter than the span
```

**Can it do the mix? Yes** — `ffmpeg -filter_complex amix`/`adelay` handles
overlay, gain and fades, and ffmpeg is already a dependency. The hard part is
never ffmpeg; it is deciding the timeline model and keeping content-addressed
caching correct once regions overlap. The mix output needs its own hash, keyed
on every contributing region, or stale mixes will be served.

**Keep the invariant:** narration chunks stay individually cached. Only the
mixdown is recomputed when an effect moves.

## 5. Render selected

**What:** select a run of cards and render them as one unit — necessary once
an effect plays beneath the two cards after it, since those three are no
longer independent.

Depends on #4. Until effects exist, per-card rendering is strictly better:
smaller units mean less re-rendering when one line is wrong.

Selection UI already half-exists — the "discuss" checkboxes could become a
general selection used by both the chat context and this.

---

## Notes for whoever picks this up

- **Do not break content-addressing.** It is why fixing one line costs 30
  seconds instead of an hour. Any feature that makes "what needs re-rendering"
  ambiguous is the wrong shape.
- **The undo stack holds text only.** If cards start referencing imported
  audio files, undo must not delete a file a restored card still points at.
  Reference-count before unlinking anything.
- **Chatterbox has no quality/speed dial** — checked. Sampling cost is per
  token, so "faster preview" always means *less text*, never *lower quality*.
- **Voices are global, projects are not.** Any export/import has to reconcile
  that.
