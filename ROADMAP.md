# Saga Studio — roadmap

Requested 2026-08-13. Core (import → chunk → profile → preview → render →
bake → assemble → undo) is built and working; everything below is deferred so
the core stays solid first.

Ordered by how much architecture each one disturbs.

---

## 1. Export / import a project as one file — **done, 2026-08-14**

Built as specified, with three things the sketch did not anticipate.

**One archive holds many projects.** *Export everything* is the button people
actually want — the whole library in one file — so the format carries a list of
projects rather than exactly one, and `manifest.json` is the *first* member so
reading "what is in here?" does not mean decompressing 231 MB to reach the end.

**Voice renaming breaks the cache, so hashes are recomputed on import.** The
sketch was right that a colliding clip must land as `<name>-imported` — but the
voice name is part of the chunk hash, so renaming one silently invalidates
every rendered chunk that mentions it. Import therefore hashes each card twice,
once under the archive's profiles and once under this machine's, and re-files
the cached WAV under the new name. Profiles collide the same way and are forked
the same way, for the same reason: both are global.

**Profiles too, not just voices.** The note at the bottom of this file said
"voices are global, projects are not" — profiles are equally global and were
the easier thing to get wrong.

Measured on the 28-episode library: 231 MB packed in 5s with audio (gzip level
1 — WAV does not compress, and the higher levels only spend CPU), 3 MB without.
A restore into an empty library returns all 28 documents byte-identical and
loses no rendered chunk.

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

## 4. Sound-effect cards — **done, 2026-08-14** (as audio + silence cards)

Built, with the model the sketch predicted — assemble() is now a timeline mix,
not a concatenation — but simpler fields than proposed, matching how it is
actually used:

- **`mode: "full" | "after"`** replaced `under_span`. Counting *cards* to play
  beneath was the wrong unit: what you actually know is "let the intro breathe
  for 6 seconds, then start talking". `after: N` advances the timeline cursor
  N seconds into the clip and everything that follows mixes over the rest.
- **Fades are percentages of the clip, one two-handled slider** — [10, 90]
  means ramp in over the first 10% and out over the last 10% — rather than
  absolute seconds. Volume is a plain 0–100 slider, not dB.
- **Clips are global** (`studio/clips/`, like voices), not per-project sfx
  dirs: the same intro music opens every episode. ffmpeg converts whatever is
  imported to PCM wav on the way in, so assemble never meets a codec.
- **Silence cards** came along for free: a timed cursor advance that places
  nothing.
- **No mix cache.** The suggested "hash the mixdown" was dropped: assemble is
  seconds of tensor math even for a full episode, so caching it buys nothing
  and risks staleness. Speech chunks stay individually content-addressed;
  the invariant holds.
- With it came the missing structural editing: an insert strip between every
  pair of cards, and drag-to-reorder by a ⠿ grip, both snapshotted for undo.
  Backups carry clips with the same never-overwrite reconciliation as voices —
  a clip name is not part of any chunk hash, so a rename on import costs only
  the pointer.

## 5. Render selected

**What:** select a run of cards and render them as one unit.

With #4 built, per-card caching still holds (the mix is cheap and uncached),
so this is now purely a convenience — export a stretch of the timeline to
audition, rather than a correctness need.

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
- **Voices and profiles are global, projects are not.** Import reconciles this
  by never overwriting either one — see #1. Anything else that crosses machines
  has to do the same, and has to remember that a rename changes what a chunk
  hashes to.
