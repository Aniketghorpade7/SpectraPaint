# SpectraPaint — Domain Glossary

The shared vocabulary for this project. If a word appears here, use it in this exact sense in code,
docs and conversation. This file is a glossary only — no implementation detail. Design decisions
live in [docs/design-decisions.md](./docs/design-decisions.md).

---

## People and activity

**Dealer**
The paint retailer who operates SpectraPaint, standing behind the counter with customers waiting.
The dealer, not the customer, drives the tool.

**Customer**
The person buying paint, choosing a colour for their own room.

**Consultation**
One counter-side interaction where a dealer helps a customer choose a shade. Short — minutes, not
an appointment. A consultation may be reopened later if the customer returns, and shows exactly the
images the customer saw the first time — never regenerated ones.

**Bundle**
A renameable grouping of one client's consultations, so a dealer can keep a job's photos and renders
together. Named for how dealers actually think — in *jobs*, not in customer records.

---

## The room

**Room Photo**
A photograph of the customer's actual room, taken on an uncontrolled mobile phone camera. Not a
stock template. This is the thing that distinguishes SpectraPaint from existing visualizers, which
show generic sample rooms.

**Wall Plane**
One visible flat wall face in a room photo. A typical photo contains two or three. Each is coloured
independently, because faces at different angles to the light differ in brightness, and that
difference is what makes the room read as three-dimensional rather than flat.

Note: a wall plane is a *face as seen in the photo*, not a physical wall. One physical wall
interrupted by a corner is two planes; one physical wall split visually by a wardrobe is still one.

**Ceiling Plane**
One visible flat ceiling face in a room photo. Typically one per photo, rarely more. Like a wall
plane, it is coloured independently, carries its own base colour and light map, and has its own
alpha matte — a ceiling must never be grouped with a wall's base colour even when the two happen to
be a similar pale colour, or the room's light modelling breaks silently.

**Paintable Plane**
The generic term for any paintable surface in a room photo — a wall plane or a ceiling plane. Where
a plane's kind matters, it carries a **surface** of `wall` or `ceiling`. Used in code and in the
REST contract (`surface` field on each plane); "wall plane" and "ceiling plane" are the specific
kinds.

**Accent Wall**
A single wall plane deliberately painted a different shade from the rest of the room. A common and
commercially significant upsell — dealers will ask for it.

---

## Colour and paint

**Shade**
A specific paint colour a dealer can actually sell, identified by a **shade code**. Always a real
saleable product, never an arbitrary colour value. "Colour" is the general concept; a **shade** is a
colour you can buy.

**Shade Code**
The dealer-facing identifier for a shade, e.g. `AP-2140`. The primary way a shade is looked up,
because the customer usually points at a chip and reads out its code.

**Shade Family**
A grouping of related shades used for browsing — neutrals, blues, earth tones. A property of the
catalogue, defined by the manufacturer.

**Finish**
The surface quality a shade is sold in — matte, satin, gloss. **Separate from the shade, not part
of it**: the same colour is sold in several finishes.

**Catalogue**
The *data*: the set of shades a dealer sells, with their codes, names, families and colour values.
Digital, queryable, versioned, and swappable so the app can serve more than one manufacturer.

**Fandeck**
The *physical artefact*: the printed book of paint chips on the shop counter. Distinct from the
catalogue, which is its digital counterpart. The fandeck remains the better surface for judging
colour, since printed chips are more colour-accurate than a monitor and can be held against a real
wall. SpectraPaint does not try to replace it.

**Colour Difference (ΔE00)**
The standard measure of how far apart two colours are perceptually, using the CIEDE2000 formula.
Always ΔE00 in this project — never an older ΔE formula, since they disagree materially at the small
magnitudes that matter for paint.

---

## How a repaint is described

**Base Colour**
The single colour value representing the paint currently on a wall, as it appears under full light.
Shared across every wall plane that carries the *same* existing paint — never estimated separately
per plane, or the brightness differences between planes would be erased and the room would flatten.

**Light Map**
How much light falls on each point of a wall, obtained by removing the base colour from the
photograph. It carries shadows, texture, corner falloff and gradients. Repainting replaces the base
colour and leaves the light map untouched — which is why shadows survive without ever being handled
as a special case.

**Realistic Mode** / **True Colour Mode**
The two ways a repaint can be shown. **Realistic mode** tints the shade by the colour of the light
actually in the room, so the wall belongs to its surroundings — the default. **True colour mode**
shows the shade as it would appear under neutral white light, matching the printed chip. Both are
legitimate; they answer different questions, and the customer will eventually ask both. Every saved
render records which mode produced it.

**Alpha Matte**
The soft-edged description of which pixels belong to a wall plane, where boundary pixels are
partially covered rather than fully in or fully out. Distinct from a hard mask; real photographic
edges are soft, and hard edges are the clearest visual sign that an image has been altered.

**Pixel Readout**
The on-demand display of the colour of the single pixel under the cursor on the image being shown,
as RGB and approximate CMYK. A reading of the *simulated image* — the photo or the repaint — and
never a Shade: it says what the screen shows, not what the paint will be, which only the fandeck
settles. The CMYK is always approximate, because the images are RGB.

---

## Objectives vocabulary

**Recolouring**
Rendering a wall in a *chosen* shade. Does not require knowing the wall's current colour accurately.

**Shade Reading**
Determining what shade a wall currently is, and finding the nearest match in the catalogue. Requires
genuine colour accuracy, and is therefore much harder than recolouring. Currently deferred — see
[docs/handoff/objective-2-colour-accuracy.md](./docs/handoff/objective-2-colour-accuracy.md).
