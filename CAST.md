# Cast

*Specified 2026-08-23. Not built. This is the shape agreed before any code.*

**The idea:** a character, a location or a prop is a **thing the library knows**, not a
filename somebody remembered. It owns reference artwork, it can own a voice, and a
visual card points at it by name. Painting Maisie in her office becomes "paint
`@maisie` in `@maisie-office`", and the pictures stop drifting because they are all
painted against the same plates with the same words.

**Status: agreed, unbuilt.** The notes below are why it is shaped the way it is.

---

## 0. What is actually broken

Not a hunch. This is episode 4 of Saga, today.

A visual card's `ref` is a string naming a file in the global pool. There is no such
thing as a reference image in this codebase: there is only *some other output that
happened to look right*. Four separate causes of drift follow from that, and only one
of them is fixed by a registry.

**1. A reference is a filename, not a thing.** Compare the two halves of the studio.
Voice has `profiles.json`: thirty named entities, each with reference clips, an
`active` selector, and dials. A card says "speak as `maisie`". Images have no
equivalent. A card says "look like `jotto-new-4`".

**2. Output and reference share one namespace.** Everything painted lands in `media/`
under an auto-name. To promote one to a reference you find it in a `<select>` of a
hundred and eighty options reading `04-maisie-ardilla-p-i--11-new-3`. The pool tree
that just shipped makes that pile browsable; it does not make a picture *canon*.

**3. Style lives in prose and is retyped per card.** In episode 4 alone:

| card | prompt begins |
|---|---|
| 6  | `Adventure time style, a detective's case file` |
| 10 | `Adventure time style external scene` |
| 15 | `vector art in the style of Adventure Time` |

Three phrasings of one intent, hand-typed, in one episode. Every card independently
re-derives the show's look. No card-level fix touches this.

**4. References are an unlabeled bag.** `_paint_nanobanana` sends
`[img, img, img, text]`. The code comment says "a face from one, a palette from
another", but the model is never told which is which. Send four references without
saying what each is for and you get blending.

And the character bible has nowhere to live: card 16 carries seventeen names in `gen`
(`jotto`, `maisie`, `maisie-new`, ... `jotto-new-19`). The whole Maisie design
exploration is buried in one timeline card's reject pile.

---

## 1. Decisions

Ruled on in conversation:

| question | decision |
|---|---|
| name | **Cast** |
| voice | **link** to `profiles.json`, do not absorb it |
| kinds | **one `kind` field**, free values, no behaviour difference |
| storage | a **registry**, not a chunk type |
| one of them | a **cast member** (never a *card*, see below) |

**"Card" is reserved and must stay reserved.** This app already means "a chunk in the
timeline" by it. If Maisie were a card and card 16 were a card, every sentence in
every code comment would need a disambiguator. A cast member is a cast member; a card
is a thing the listener experiences.

### 1a. One decision the code overruled

Series ownership was agreed as "a pointer in the doc". **The code already decided
otherwise, and better.** `studio.py`:

> A series is a playlist over the library: an ordered list of project names kept
> entirely OUTSIDE the projects it names. Not one byte of a doc.json says which shelf
> a story sits on, and that is the whole point. A story stands alone, is shared alone,
> plays alone.

Writing `series: "saga"` into `doc.json` breaks that invariant: a story shared to
darkride would carry its shelf with it. And it is unnecessary, because `series_state`
already resolves one-shelf-per-story through the `claim` rule (the shelf that was
*made* first wins, never the one that happens to sort first).

So: **no pointer.** Add a derived helper instead.

```python
def series_of(name):
    """Which shelf a story sits on, by the same claim rule series_state uses:
    the shelf MADE first wins. Derived, never stored, and a story still knows
    nothing about where it is shelved."""
    for slug, rec in series().items():
        if name in (rec.get("order") or []):
            return slug
    return ""
```

That is the whole cost of the thing the pointer was for.

### 1b. Flat namespace, not tiers

I floated project → series → global shadowing. Dropped. Reasons: `profiles.json` is
flat with thirty of them and has never once been the problem; shadowing means two
members can answer to one name and the author cannot see which won; and promotion
becomes a rename, which breaks every card pointing at it.

**Cast slugs are globally unique.** A `scope` field decides where a member is *shown*,
never which member is *found*. Promotion edits one field and breaks nothing.

---

## 2. `cast.json`

Beside `profiles.json` and `series.json`, same shape of file, same manners: missing or
unreadable reads as empty, so a library that has never heard of the cast behaves
exactly as one did before.

```jsonc
{
  "maisie": {
    "kind":  "character",          // free text: character, location, prop, vehicle…
    "title": "Maisie Ardilla",     // what a human calls it
    "brief": "squirrel PI, trenchcoat, fedora, tired, competent, mid-thirties",
    "scope": "saga",               // "" = shows everywhere; else a series slug
    "voice": {                     // engine → profile name in profiles.json
      "chatterbox": "maisie",
      "omnivoice":  "maisie - omnivoice"
    },
    "key":   "trench-3q",          // the default plate for the whole member
    "plates": {
      "trench-3q":      {"file": "p1.webp", "look": "trenchcoat", "view": "3/4"},
      "trench-sheet":   {"file": "p2.webp", "look": "trenchcoat", "view": "turnaround"},
      "trench-angry":   {"file": "p3.webp", "look": "trenchcoat", "view": "expression"},
      "suit-blue-3q":   {"file": "p4.webp", "look": "spacesuit blue", "view": "3/4"},
      "suit-blue-sheet":{"file": "p5.webp", "look": "spacesuit blue", "view": "turnaround"}
    },
    "created": "2026-08-23 18:40"
  },

  "maisie-office": {
    "kind": "location", "title": "Maisie's office", "scope": "saga",
    "brief": "inside a sycamore, pink desklamp, case files, rain on the glass",
    "key": "day-wide",
    "plates": {
      "day-wide":   {"file": "q1.webp", "look": "day",         "view": "wide"},
      "night-wide": {"file": "q2.webp", "look": "night, rain", "view": "wide"},
      "night-desk": {"file": "q3.webp", "look": "night, rain", "view": "detail"}
    }
  },

  "adventure-time": {
    "kind": "style", "title": "Adventure Time", "scope": "saga",
    "brief": "flat vector, thick even line, cel shading, saturated but muted, no gradients",
    "key": "board", "plates": {"board": {"file": "board.webp"}}
  }
}
```

Every field is optional except `plates`. `voice` may be absent (a location has no
voice). `scope` may be absent (shows everywhere).

### Plate files

```
ROOT/cast/<slug>/<file>.<ext>
```

**A plate's file name is not its slot name.** The slot is a key in `plates` and the
file is whatever it was filed under, because a slot gets renamed (`3q` becomes
`3q-trench`) and a file must never be moved once a stored `ref` can name it. Renaming
a slot rewrites one key and touches no bytes.

**Plates are not in `media/`, deliberately.** That separation *is* the fix for cause
2: canon lives somewhere a shot cannot be mistaken for it, and the pool stays what it
is, the place output lands. A visual card's `media` field continues to name pool files
only. A plate is never a shot.

**Candidates live here too, and are simply not in `plates`.** A member may carry
`"candidates": ["c1.webp", ...]`: files in its own folder that no slot has claimed.
Accepting one adds a key to `plates` and moves nothing. See §7.

### Looks

A plate carries a `look` and a `view`, and this is not decoration. Maisie in a
trenchcoat and Maisie in a spacesuit each want a turnaround, a three-quarter and an
expression or two, so a flat list of slots reaches fourteen tiles with no structure in
it before she has been anywhere interesting.

- **`look`** is the outfit, or for a location the time of day and weather: `trenchcoat`,
  `spacesuit blue`, `night, rain`. It is what the board groups the grid by.
- **`view`** is the angle or purpose within a look: `3/4`, `front`, `back`,
  `turnaround`, `detail`, `expression`.

Both are free text, both may be empty, and neither is addressable. **The slot stays
the single key a `ref` names**, so `@maisie/suit-blue-3q` is as deep as a reference
ever goes and adding this costs nothing at the point of use.

What it buys is **duplicate this look**: copy every plate carrying `spacesuit blue`
into a new look called `spacesuit red`, then repaint each copy against the blue
original it came from. One gesture for "she becomes a cosmonaut", instead of four
separate paintings that will not agree with each other.

**A look, or a whole new member?** A look, when it is the same character: same voice,
same brief, different clothes. A whole new member when the *character* differs, like a
puppet version, or her mother, or Maisie thirty years older. Both gestures exist
because they answer different questions, and picking the wrong one shows up later as
either a cluttered grid or a cast that has three Maisies in it.

Same pool law applies: **never overwrite, never delete.** Replacing a plate writes a
new name and repoints `plates`, because a plate name is about to appear inside stored
card refs.

---

## 3. `ref` grows entity references

`ref_list` and `ref_store` already exist as a back-compat pair, and the field is
documented as having "worn several shapes". This is the next shape.

An item in `ref` is now **either**:

- a bare pool name, exactly as today, meaning exactly what it means today, or
- `@slug`, meaning that member's `key` plate, or
- `@slug/plate`, meaning that exact plate.

```jsonc
"ref": ["@maisie/3q-trench", "@maisie/sheet", "@maisie-office/wide"]
```

`ref_list` keeps its sanitising and gains `@` and `/`:

```python
REF_RE = re.compile(r"^@?[a-z0-9_-]{1,60}(/[a-z0-9_-]{1,40})?$")
```

Nothing migrates. Every existing card keeps a bare pool name and keeps working.

### Resolution

One function, and it is the only place that knows what an `@` means:

```python
def resolve_ref(item):
    """A ref item to (path, label). A bare name is a pool picture and labels
    itself; an @entity is a plate and says what it is FOR, which is the half
    the model was never told."""
    if not item.startswith("@"):
        return _ref_image(item), "Reference"
    slug, _, plate = item[1:].partition("/")
    e = cast().get(slug)
    if not e:
        raise ValueError(f'no cast member "{slug}"')
    plate = plate or e.get("key") or next(iter(e.get("plates") or {}), "")
    p = e.get("plates", {}).get(plate)
    if not p:
        raise ValueError(f'"{slug}" has no plate "{plate}"')
    kind = (e.get("kind") or "reference").capitalize()
    return CAST / slug / p["file"], f'{kind} reference ({e.get("title") or slug}, {plate})'
```

---

## 4. Prompt assembly

**This is the part that actually kills drift.** The registry makes consistency
possible; the labelling makes the model do it.

`generate_media` stops handing nanobanana an anonymous pile and hands it a described
one:

```
Character reference (Maisie Ardilla, 3q-trench): [img]
Character reference (Maisie Ardilla, sheet): [img]
Location reference (Maisie's office, wide): [img]
Style reference (Adventure Time, board): [img]

Style: flat vector, thick even line, cel shading, saturated but muted, no gradients.
Cast: Maisie Ardilla, a squirrel PI, trenchcoat, fedora, tired, competent, mid-thirties.
Setting: Maisie's office, inside a sycamore, pink desklamp, case files, rain on the glass.

Shot: she looks up from the case file as the door opens. Night.
```

Three things to hold to:

- **The `brief` goes in as words, next to the plate that shows it.** A picture and a
  sentence agreeing is much stronger than either alone.
- **Order is fixed:** style, then cast, then setting, then shot. Consistent ordering is
  itself a consistency lever with these models.
- **Draw Things gets the first plate as its img2img canvas and the same text.** It
  cannot take a gallery; that is a limit of the local painter, not of this design.

---

## 5. Style, in three tiers

Composed, never chosen. Each tier may carry text and plates.

| tier | lives in | example |
|---|---|---|
| series | `series.json[slug]["style"]` | Adventure Time vector art |
| story  | `doc["style"]` | this episode is night and rain |
| card   | the card's `note`, as now | the shot |

```jsonc
// series.json record gains:
"style": {"text": "flat vector, thick even line, cel shading",
          "refs": ["@adventure-time/board"]}
```

`doc["style"]` is a **new top-level doc key**, not a corner of `doc["params"]`.
`params` is the delivery bag (voice overrides, set wholesale by `/api/params`) and
style is not delivery. It must survive `load`, `save`, the copy path, and export.

### Visible, never silent

A card shows its effective style as a dim uneditable line above the prompt box, and
carries `"nostyle": true` to opt out. Prepending words an author cannot see, into a
prompt they are debugging, is the kind of magic that costs an afternoon. The rest of
this app does not do that and neither should this.

---

## 6. Promotion: the gesture that was missing

Today there is no way to make a picture canon. There is one button:

**In the variants menu (`genMenu`), and on the pool tree's context menu:
`→ make this a reference…`**

It asks three things (member, existing or new; slot name; whether this becomes `key`),
then copies the pool file into `cast/<slug>/<plate>.<ext>`. The pool copy stays, pool
law untouched.

That single gesture is most of the felt pain. `jotto-new-4` becomes
`@maisie/3q-trench` and never has to be found in a dropdown again.

### Turnarounds

A member with a key plate gets **`generate turnaround`**, which paints a model sheet
from it:

> the same character, model sheet, front / three-quarter / profile / back, neutral
> grey background, consistent height and proportion, no text

Kept **whole** as one plate named `sheet`. Not sliced: nanobanana reads a sheet fine
as a single reference, and slicing is fiddly work that buys nothing.

---

## 7. UI

The Cast has **two jobs**, and one surface for both is what would make it bad.

*Reaching* is "put Maisie on this card". That wants a narrow list, always visible,
next to the deck. *Working* is "organize her plates, paint a turnaround, try three
coats, decide which is canon". That wants a board, and it wants width.

### 7a. The list: a Cast tab in the sidebar

Beside Stories, Voices, Media and Publish. Rows in the same idiom, grouped by `kind`
under foldable headers exactly as the shelves and the pool tree already do, folds in
`localStorage` beside `saga.sfold` and `saga.mfold`. Filtered by `scope` against the
open story's shelf, with a show-all toggle. `QRY` / `setQry` / `hits` take a fifth
list for free.

Drag a row onto a card to add `@slug` as a reference. Same drag the pool tree
implements. Double-click opens the board.

### 7b. The board: it takes over the deck

Not a modal, because this app has none and is right not to. Not a fourth column,
because `#right`'s own comment settles that: three panels of chrome around one column
of cards is more frame than picture. The board replaces `<main id="main">` and a
`#castbar` sits above it the way `#draftbar` does, saying whose board this is and how
to get back.

```
┌─────────┬────────────────────────────────┬────────┐
│ Stories │ ✎ Maisie · character  [← deck] │Inspect │
│ Voices  ├────────────────────────────────┤        │
│ Media   │ brief  squirrel PI, trenchcoat │        │
│▸Cast    │ voice  maisie ▶  maisie-omni ▶ │        │
├─────────┤                                │        │
│CHARACTERS  trenchcoat          [dup ⧉] │        │
│ ● Maisie│ ┌─────┐┌─────┐┌─────┐          │        │
│   Reggie│ │★ 3q ││sheet││angry│          │        │
│LOCATIONS│ └─────┘└─────┘└─────┘          │        │
│   office│                                │        │
│   docks │ spacesuit blue         [dup ⧉] │        │
│STYLES   │ ┌─────┐┌─────┐                 │        │
│   adv-t │ │ 3q  ││sheet│                 │        │
│         │ └─────┘└─────┘                 │        │
│         │                                │        │
│         │ CANDIDATES                     │        │
│         │ ┌───┐┌───┐  → accept into slot │        │
│         │ └───┘└───┘                     │        │
│         │ ┌──────────────────┐ [Paint]   │        │
│         │ │ same suit, red   │           │        │
│         │ └──────────────────┘           │        │
│         │ [turnaround][expressions]      │        │
└─────────┴────────────────────────────────┴────────┘
```

**Mode, not place.** `body.dataset.mode = 'cast'`. Opening a story from the sidebar
returns to the deck, because opening a story is an intent to edit it. The Cast tab
stays selected either way. `#stagedock` is untouched and stays mounted, so a render
you set going keeps playing while you work on plates.

### 7c. Plates and candidates are different things

**Painting in the board produces candidates, never canon.** You accept one into a
named slot. This is the `gen` shortlist a card already keeps, one level up, and it is
what lets the board be a place to try things: canon should be chosen, not
accumulated. A rejected candidate stays in the folder and stays out of `plates`.

**Removing a plate unlinks it, it does not delete it.** Same law as dropping a variant
from a card's shortlist, and the reason no undo machinery is needed here.

**Two duplications, on the two things worth duplicating.** `⧉` on a look's header
copies every plate in it into a new look and leaves each copy pointing at the original
it came from, so the repaint that follows has something to match. `⧉` on the member in
the sidebar copies the whole thing, brief and voice bindings included. §2 covers which
one a given change wants.

Per plate, on right-click: rename the slot, make it key, paint a variant *of this
one*, open it in your viewer, remove it. Drag to reorder. Drop files from Finder onto
the grid to add plates, the gesture `#drop` already teaches.

### 7d. Painting inside the board

**It must use the member's own plates as references, or the drift simply moves up a
level** and you get a turnaround that does not match the portrait it came from. So
Paint here sends the key plate (plus any plate you have selected), the `brief` as
words, and the series style, assembled exactly as §4 describes.

The preset buttons are prompts that do this well: **turnaround** (§6), **expression
sheet**, **this outfit from three angles**. Nothing a typed prompt could not do; they
exist because the phrasing matters and should not have to be remembered.

### 7e. Three doors to a new cast member

1. The Cast tab's **+ New Member**.
2. A painted variant on a card: **`→ make this a reference…`** (§6).
3. **A voice profile becomes a character.** `profiles.json` holds thirty profiles and a
   good number of them are characters that exist nowhere else in the app. One button
   in the profile editor makes a cast member already linked to that profile, look to be
   filled in later. It is the fastest way to populate a cast that already half exists.

### 7f. The reference picker on a card

The flat `<select>` at `studio_ui.html:3796` becomes a thumbnail grid grouped by
member: cast members first, then the raw pool for what the cast does not cover. The ref
chips stay as they are; a chip for an entity reads `@maisie/angry` and is dropped the
same way.

### 7g. One constraint, to keep a door open

**The board must never read `DOC`.** It is a function of a member and its plates and
nothing else. That costs nothing now, and it is what would make serving the same
component standalone at `/cast` a small job rather than a rewrite, should the board
ever want to be its own window on a second display. The Stage already proves that
path works.

### 7h. Paint a Variant, on the card itself

The board's anchored repaint (§7c, §7d), grown app-wide: **paint a variant of this
one** on a visual card's picture — its right-click menu and the variants menu — arms
the card's paint row to send the CURRENT picture as the FIRST reference, ahead of the
card's own refs and the style tiers, behind a label saying it is the one being varied.
First matters twice: Draw Things paints over the first reference, and nanobanana's
gallery reads it as the canvas rather than advice. So a repaint keeps the picture it
starts from and changes what the prompt asks, instead of wandering.

The mode is sticky, like the board's target: each later paint varies whatever the card
shows *then*, which is the refinement loop — paint, nudge the prompt, paint again,
each pass anchored to the last. And it is visible, never silent (§5's rule): an
`against: <name> ✕` chip in the paint row, the Paint button reading **Paint a
Variant**, both gone when the chip is dismissed or the row closed — the mode cannot
outlive its own visibility.

---

## 8. Export, archive, copy

`plan_export` learns a fourth closure beside `media_of`, `media_refs_of` and
`media_history_of`:

```python
def cast_of(doc):
    """The cast members a project's cards reach for, and the plates they name.
    A copy that loses these can no longer paint in the story's own style, which
    is the same reason media_refs_of exists."""
```

Cast members and their plate files ride in the **archive** (a project copy needs them)
and in **series export**. They do **not** ride in the web export: `media_of` is what a
published story shows, and a plate is never shown. That boundary is already stated in
`media_of`'s docstring and must not be widened.

`import_archive` merges `cast.json` by slug on the same terms as profiles: an existing
slug is kept, never overwritten.

---

## 9. Back-compat

| thing | behaviour |
|---|---|
| no `cast.json` | everything works exactly as today |
| existing `ref` strings | untouched, unmigrated, still pool names |
| existing cards | unchanged on disk until repainted |
| `doc["style"]` absent | no style tier, prompt is the note, as today |
| Draw Things | first plate as canvas, labelled text, same as it gets now |

Nothing in this spec requires a migration script. That is a deliberate constraint, not
a happy accident: forty projects and three gigabytes are not worth a one-way door.

---

## 10. Build order

Each step is useful alone and shippable alone.

**1. Registry and plates.** `cast.json`, `CAST` dir, `cast()` / `save_cast()`,
`/api/cast/*`, the Cast tab (§7a) and the board (§7b) as a read-and-arrange surface:
plates, drag to reorder, drop from Finder, set key, rename a slot. No painting in it
yet. Nothing renders differently; you can file Maisie.

**2. Entity refs and labelled prompts.** `REF_RE`, `resolve_ref`, `generate_media`
rebuilt around labelled parts, thumbnail ref picker. **Character drift stops here.**

**3. Promotion, candidates and turnarounds.** All three doors of §7e, the
candidates row and accept-into-slot (§7c), and painting inside the board with the
preset prompts (§7d). This is the ergonomics step, and it is what makes step 1 worth
having filled in.

**4. Style tiers.** `series.json[slug]["style"]`, `doc["style"]`, the visible
effective-style line, `nostyle`. **Style drift stops here.**

**5. Archive and export closure.** `cast_of`, plates into archives, merge on import.

Steps 1 to 4 are independent of the pool and of shelves. Do them first.

---

## 11. Deliberately not in v1

- **No shadowing or inheritance between members.** No "Maisie in her winter coat is a
  child of Maisie". Two members, or two looks. Inheritance in an asset graph is a
  thing you can never take back out.
- **No automatic consistency checking.** Nothing scores whether a render matched its
  plates. Interesting, unbuilt, and not worth blocking on.
- **No slicing turnaround sheets.** See §6.
- **No cast members in the timeline.** The Cast is not a card type and must not become
  one. A card is a thing the listener experiences; a cast member is a thing the author
  paints against.
- **No audio GC.** `audio/` is three gigabytes across 4,620 files and it does need a
  sweep that walks every doc and deletes what nothing references. That is real, it is
  worth doing, and it has nothing to do with the Cast.

---

## 12. What this does not fix

The pool is still one flat directory. The tree that just shipped groups it by the
story that placed each picture, which makes it browsable; it does not scope it. If
after the Cast is in use the pool still feels like a jumble, the fix is a lookup order
(`series media dir → global pool`) rather than a migration, because cards name assets
and never path them. That property is worth protecting in everything above: **no
change in this spec introduces a path into a document.**
