# Lighting concepts

An appendix for engineers who are new to stage lighting. It covers the vocabulary
used by DMX fixtures, lighting desks, and fixture-definition formats; the last
section says which of these words Stargarden uses.

## DMX512

- **DMX512** ("DMX") is the wire protocol between a controller and fixtures: an RS-485 serial
  stream, refreshed up to ~44 times a second, carrying up to 512 8-bit values.
- A **universe** is one such stream of 512 **channels** (also *slots* or *addresses*), each holding
  a value 0–255. Larger rigs use several universes.
- Fixtures are **daisy-chained** (DMX in → DMX out, 5-pin or 3-pin XLR) and the last one gets a
  120 Ω **terminator**. Order on the chain does not matter; addressing does.
- Each fixture is set to a **start address** and listens to a contiguous block of channels from
  there; the block size is its **footprint**. Two fixtures given the same address behave identically.
- A controller reaches the wire through a **DMX interface**: a USB adapter (e.g. Enttec DMX USB
  Pro), or an Ethernet node speaking **Art-Net** or **sACN (E1.31)**, which carry universes over IP.
- **RDM** (Remote Device Management) is an optional back-channel over the same wire for reading and
  setting fixture parameters (address, mode) remotely.

## Fixtures

- A **fixture** (also *luminaire*, *unit*, *head*) is one physical light. **Wash** fixtures flood an
  area with color; **spots/profiles** project a hard beam; **moving heads** add pan/tilt; **bars**
  and **panels** are strips or grids of LEDs; a **strobe** produces short bright flashes.
- A **fixture type** (Lightkey/QLC+: *fixture profile* or *definition*) describes a model of
  fixture: its channel layouts and physical properties. A fixture in a rig is an *instance* of it.
- Most fixtures offer several **DMX modes** (Lightkey: *personalities*), selected on the fixture's
  own menu. A mode fixes the footprint and the meaning of every channel: a "6-channel mode" exposes
  coarse control, a "129-channel mode" exposes every LED zone individually. The controller must be
  told the same mode the fixture is set to.
- The **patch** is the table of which fixtures exist, their types and modes, and their addresses.
  *Patching* a fixture means adding it to that table.
- Manufacturers publish the per-mode channel table in the manual, often called **DMX traits**,
  *DMX chart*, or *channel map*.

## Channels and attributes

- Each channel controls one **attribute** (also *parameter*, *function*): intensity, red, strobe,
  pan, gobo, etc.
- A **16-bit** attribute uses two channels, **coarse** and **fine** (high and low byte), for
  65 536 steps instead of 256 — common for dimmers and pan/tilt.
- Many channels are **continuous** (0–255 maps to 0–100 %). Others are **range-selecting**: the
  value picks a function and sometimes a setting within it, e.g. a strobe channel with 000–002 =
  open, 003–005 = strobe, 006–050 = ramp up, 151–200 = lightning, 201–255 = random. The formats call
  these ranges **channel functions** (GDTF) or **capabilities** (QLC+, Open Fixture Library).
- Common attribute families, in GDTF's names:
  - **Dimmer** — overall intensity. Fixtures without a dimmer channel are dimmed by scaling color.
  - **ColorAdd_R / G / B / W / CW / WW / Amber / UV** — additive color mixing per emitter color
    (RGB, RGBW, RGBA…; CW/WW = cool/warm white). **ColorSub_C/M/Y** is subtractive mixing with
    flags in front of a white source; **color wheels** select fixed colors.
  - **Shutter** — open/closed; **strobe** functions (Shutter1Strobe, …StrobePulse, …StrobeRandom)
    live on it. **StrobeFrequency/StrobeRate** and **StrobeDuration** set flash speed and length.
  - **Pan / Tilt**, **Gobo**, **Zoom**, **Focus**, **Iris**, **Prism**, **Frost** — beam
    attributes of moving heads and spots.
  - **Color temperature (CT) presets**, **color macros**, **program/auto macros**, **sound-active
    mode** — built-in effects; usually parked at 0 when a controller drives the fixture.
- **Feature groups** (GDTF) bundle attributes for the UI: Dimmer, Color, Beam, Position, Gobo,
  Focus, Control.

## Multi-cell fixtures

LED bars, panels, and multi-lamp fixtures contain several independently controllable light
sources. Every product calls the sub-unit something different:

| Product | Sub-unit | Whole-fixture control |
|---|---|---|
| GDTF / grandMA3 | *geometry* (a *Beam* geometry); *subfixture*, informally *cell* | attributes on the parent geometry apply top-down |
| ETC Eos | *cell* | *master*; "mastered cells" scale with the master |
| QLC+ | *head* | — |
| ChamSys MagicQ | *element* | *general element* |
| Lightkey | *beam* | — |
| Open Fixture Library | *pixel* (in a *matrix*; *pixel groups*) | — |
| Manufacturer manuals | *zone*, *segment*, *section*, *pixel*, *group* | *master dimmer* |

- A **master** attribute (typically a master dimmer or a master strobe) applies to all cells at
  once, on top of the per-cell channels. Eos's **mastered cells** rule: cell output = cell level ×
  master level.
- Higher channel-count modes expose more cells; low modes expose one. Some modes expose one
  attribute per cell (e.g. per-zone RGB) but share others (one dimmer, one strobe) across a group
  of cells.
- **Geometry** places cells physically. GDTF describes a fixture as a tree of geometries with
  positions; repeated cells are *geometry references*. Consoles use it for **pixel mapping**
  (playing an image or effect across cells by position) and for laying out the selection grid.

## Desks and software

- **Consoles/desks**: grandMA (MA Lighting), Eos (ETC), Hog (High End), MagicQ (ChamSys). These
  are also available as PC software with or without hardware wings.
- **Software controllers**: QLC+ (open source, cross-platform), Lightkey (macOS), plus DAW-style and
  media-server tools. **OLA** (Open Lighting Architecture) is a daemon that abstracts DMX interfaces
  and protocols for other software.
- Programming vocabulary: a **look** or **scene** is a set of attribute values; a **cue** is a
  stored look with **fade** (transition) times, played in a **cue list**; a **chase** steps through
  looks; **effects** modulate attributes over time (sine, ramp, random) across selected fixtures; a
  **palette/preset** is a reusable attribute value ("deep blue", "center stage"); the **grand
  master** scales all output and **blackout** kills it; **highlight** flashes the selected fixture
  for identification.

## Fixture-definition formats

- **GDTF** (General Device Type Format, DIN SPEC 15800) — the open standard from MA Lighting,
  Robe, and Vectorworks; XML plus 3D models in a zip. Vocabulary: FixtureType → DMXMode →
  DMXChannel (with byte offsets) → LogicalChannel (Attribute) → ChannelFunction (DMX range →
  physical value); Geometry tree. Library at gdtf-share.com. **MVR** is the companion format for
  whole rigs.
- **Open Fixture Library** (OFL) — community JSON definitions with exporters to QLC+ and others.
  Vocabulary: modes, channels, capabilities, matrix / pixelKeys / pixelGroups, template channels.
- **QLC+** `.qxf` — XML: modes, channels with capabilities, heads.
- **Lightkey** `.lightkeyfxt` — NSKeyedArchiver plist: personalities, capabilities (per channel,
  with DMX-range settings), beam layout.

## Stargarden's vocabulary

Stargarden's lighting code uses the GDTF/Eos words: a **fixture type** has **DMX modes**; a mode has
**cells** (its light-emitting sub-units, each with a position and a kind — color or white) and
**DMX channels**, each carrying one **attribute** (named as in GDTF: `Dimmer`, `ColorAdd_R`,
`ColorAdd_CW`, `Shutter1`, `StrobeFrequency`, …) on either a cell or a parent geometry (a
**master**); range-selecting channels carry **channel functions**. The engine writes attribute
values per cell; the renderer resolves masters with Eos's mastered-cells rule. See
`src/stargarden/lighting/fixtures.py`; fixture reference material lives in `docs/fixtures/`.

## References

- GDTF file spec and attribute list: <https://www.gdtf.eu/gdtf/file-spec/> ·
  <https://www.gdtf.eu/gdtf/attributes/attributes/>
- grandMA3 help: glossary, subfixtures, parent/child concept: <https://help.malighting.com/grandMA3/>
- ETC Eos multicell fixtures:
  <https://www.etcconnect.com/WebDocs/Controls/EosFamilyOnlineHelp/en/Content/08_Manual_Control/Multicell_Fixtures.htm>
- QLC+ fixture definition editor: <https://docs.qlcplus.org/v4/fixture-definition-editor/modes>
- ChamSys MagicQ head editor: <https://secure.chamsys.co.uk/help/documentation/magicq/head-editor.html>
- Lightkey fixture profiles: <https://lightkeyapp.com/en/help/fx-profiles>
- Open Fixture Library format: <https://github.com/OpenLightingProject/open-fixture-library/blob/master/docs/fixture-format.md>
