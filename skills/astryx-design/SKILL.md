---
name: astryx-design
description: The astryx design language, distilled from Canvas — theme tokens, colour meaning, surfaces, type, motion, and above all PRESENCE (agents shown as faces that travel to what they touch). Read this before you build or change ANY human-facing UI: an observatory view, a Canvas component, a canvas page, a voice or sensing control.
---

# astryx design

Canvas is the reference. The owner's words: "so beautiful and you enjoy using the UI; perfect
UX". Everything here is lifted from code that already ships (`canvas/web/src/`: `index.css`,
`themes.ts`, `ui.tsx`, `CanvasView.tsx` PresenceLayer/CrewStrip, `VoiceDock.tsx` Orb,
`VoiceMode.tsx`; the page kit in `bridges/canvas_shell.py`). When this file and that code
disagree, the code is the truth and this file is stale. Fix it.

**The idea in one line:** astryx is many agents working together, so the UI shows *who* is
attending to *what*, calmly, in one shared palette. It is not a dashboard of widgets. It is a
room you can see into.

## 1. One theme, every surface

Every colour is a token from `canvas/web/src/themes.ts`. The observatory imports that same file,
so the surfaces cannot drift. Never write a hex value in a component.

| token | meaning | Tailwind alias (React apps) | page kit (canvas pages) |
|---|---|---|---|
| bg / bg2 | page / chrome (sidebars) | `bg-void` / `bg-ink-900` | `--cv-bg` / `--cv-bg-2` |
| panel / panel2 | raised surface / hover, input wells | `ink-800` / `ink-700` | `--cv-panel` / `--cv-panel-2` |
| line / line2 | hairline / stronger border, focus | `border-line` / `line-strong` | `--cv-line` |
| fg / dim / mute | primary / secondary / tertiary text | `text-fg` / `fg-dim` / `fg-mute` | `--cv-ink` / `--cv-dim` / `--cv-mute` |
| accent | the subject: live, attending, *this* agent | `violet` | `--cv-accent` |
| accent2 | its companion: gradients, links, the other voice | `cyan` | `--cv-accent-2` |
| good / bad / warn | direction and state only | `good` / `bad` / `warn` | `--cv-good` … |
| on | text sitting on an accent fill | `text-on` | `--cv-on` |

- React apps read `--t-*` (applied on `<html>`). Canvas pages read `--cv-*`, which the shell maps
  from the viewer's theme.
- **Canvas 2D / WebGL drawing** can't use CSS vars. Read them with `getComputedStyle(document.documentElement)`
  and re-read when the theme changes. Copy `useTokens()` from `VoiceDock.tsx`.
- There are light themes too. `T` cycles the palettes, so look at your UI in Astryx *and* in a light
  theme before you ship.
- Tints come from `color-mix(in srgb, var(--t-accent) 14%, transparent)`, never from a new
  colour. `bg-fg/[.06]` is the hover wash; `bg-fg/[.04]` is a well.

## 2. Colour means something

- **accent** = attention. An agent working, a mic listening, the selected thing. If it glows, something is
  attending to it right now.
- **accent2** = the companion. It is the reply voice in the orb (you are accent, they are accent2), links,
  and the far end of the signature gradient.
- **good / bad / warn** are for state and direction only: a live dot is good, muted is warn, hang-up is
  bad. They are never decoration.
- Everything else is **fg / dim / mute**. Grey is the default and colour has to be earned.
- **The signature** is `.sig` (accent→accent2 at 135°, a fill), `.sig-text` (the same gradient as
  text) and `.ring-sig` (a ring plus a long accent2 shadow). Use at most one per screen: the primary
  action, the agent's name in a headline (`<span className="italic sig-text">painter</span> is
  painting`), or the ring around a focal face.

## 3. Surfaces

- `.glass` (80% bg2, `backdrop-blur(18px) saturate(1.2)`, hairline): chrome that floats *over*
  content, like the voice dock, a toast, the "Point at anything" hint, or a side sheet.
- `.solid` (panel plus hairline): popovers, speech bubbles, menus.
- Radii: controls `rounded-lg`/`rounded-xl`, cards and buttons `rounded-2xl`, floating sheets
  `rounded-[28px]`, faces and status dots `rounded-full`. Page-kit cards use `--cv-radius` (16px).
- Shadows are soft and dark: `shadow-2xl shadow-black/25`–`/30` on floating things, and nothing on flat ones.
- **The aurora** is two blurred accent/accent2 discs drifting over 38s at 11–16% opacity (10% on
  light). It is the *only* ambient background motion. Don't add a second one.

## 4. Type

- **Inter** for everything (15px body). Scale steps: 11 / 12 / 13 / 15, then headline sizes.
- **Instrument Serif** for the one emotional line on a screen, such as "painter is painting" at `text-4xl`
  or the agent's spoken reply at 21px. Never for UI chrome.
- **JetBrains Mono** for live machine lines at 11–12px: progress, a step in flight, what was just
  heard. Pair it with `.shimmer` while the line is still live, and drop to `text-fg-dim` once it settles.
- Small labels are 11–12px, `uppercase tracking-wider` (`.08em`), `fg-mute`.
- Every number is `tabular-nums`, so counters never jitter sideways.

## 5. Motion

Library: `motion/react` in the apps, CSS transitions in canvas pages.

- **Enter**: opacity 0→1 with a small travel (`y: ±4–8` or `scale: .9–.98`). **Exit** is faster and
  simpler (opacity, a few px). Wrap anything that comes and goes in `AnimatePresence`.
- **Springs, by weight:**
  - sheets and panels: `damping 26–30, stiffness 260–320` (snappy, no bounce)
  - a highlight frame moving to a new element: `damping 24, stiffness 180`
  - **a face travelling across the page: `damping 18, stiffness 90, mass 1.1`**. It is slow and has weight, so
    it reads as someone walking over, not a cursor teleporting.
- UI transitions run 150–600ms and ease out. Ambient loops run 1.8–3.2s: a working bob, a highlight breathing,
  a `breathe` opacity cycle.
- **Loops are for living states only** (working, listening, connecting). An idle thing is still.
- **Smooth every live signal.** For example, the mic level is `l * 0.7 + x * 0.3` per frame. Jitter reads as noise.
- **Reduced motion:** `index.css` kills CSS animations and transitions globally, but a `<canvas>`
  loop or a JS-driven animation must check `matchMedia('(prefers-reduced-motion: reduce)')` itself
  and draw a still frame (the Orb's `still`). The page kit honours it too, so check it in `reduced.png`.

## 6. Presence: the signature of astryx

This is what makes astryx feel like a collaboration rather than an app. When an agent acts on a
surface, **the surface shows who and where, never a bare spinner.**

- **A face, not a name.** `Avatar` uses the agent's portrait if it has one, otherwise a conic gradient
  whose hue comes from the name (the same agent is always the same colour) with a soft
  hue-tinted glow. Humans (owner, `cv-*`) get a plain neutral disc, so agents and people never
  look alike.
- **The live cursor (`PresenceLayer`).** An agent's face *travels* to the element it is working on.
  The agent sets `presence.py focus canvas:<id> --target <selector> --say "…"`, and the face springs
  there with the heavy spring above. The element gets a frame (2px accent border, a 6px accent halo at
  14%, and a fill breathing 15→35% over 1.8s). The face gently bobs (`y [0,-5,0]`,
  `rotate [0,-3,3,0]`, 2.2s) and carries a partial spinning ring (`border-t-transparent`).
- **A speech bubble beside the face.** It is `.solid`, `rounded-2xl rounded-tl-md`, with the agent's name in
  accent at 11px semibold and its line at 12px. The line is mono plus shimmer while live and dim once done,
  clamped to two lines.
- **States, and how each one reads:**
  - *working / moving*: an accent ring and glow, the bob, the spinning arc.
  - *done*: a good ✓ badge. It stays where it worked for ~45s so the viewer sees *where*, then goes idle.
  - *idle*: smaller (34px), benched in a row along the bottom edge, with a plain dark shadow and no colour.
- **Self-healing.** "Working" with no new step for 3 minutes reads as done, and presence older than
  20 minutes reads as idle. A UI must never show an agent busy forever because a row went stale.
- **The crew strip.** Overlapping 26px faces (`-space-x-2`, `ring-2 ring-void`) show who is on this
  surface. A face turns `ring-violet` while it is busy.
- **An empty surface is a promise.** It is the `.easel` (accent radial washes plus a faint diagonal
  hatch), with the keeper's face floating in a `ring-sig` and a line like "waiting for the first
  brushstroke…". A blank area is a broken promise.

## 7. State is a word, a dot and a shape

- Every async phase has a human label: "Waking the microphone…", "Catching that…", "painter is
  thinking", "Opening a line…". The status sits as a dot plus one word in the header (`good` live,
  `warn` + `animate-pulse` connecting, `warn` tint when muted).
- A **muted or paused** thing goes grey: the orb redraws in `mute`, and the mute button sits on a
  `bg-warn/15 text-warn` wash and says "Muted". Being off should be obvious at a glance and still calm.
- Errors say what to do: "Microphone unavailable. Voice needs mic permission, and https or localhost."
- Live text regions get `aria-live="polite"`.

## 8. Senses: voice and listening

The voice orb (`VoiceDock.tsx`) is the reference for anything that hears or speaks:

- It is a **canvas-drawn blob** whose edge is a few slow sine harmonics, swelling with the smoothed
  level. It has a radial halo, an accent2 core shading to an accent rim, a companion blob drifting inside, a
  soft shadow side and a specular highlight. It has depth without washing out to white.
- **Who is speaking changes the hue.** You are accent and the agent is accent2. The level ring shows only
  when live and unmuted. *Connecting* is a single accent2 arc sweeping round. *Muted* redraws the whole thing in `mute`.
- A sense that runs in the background (the ear) is **quiet by default**: a small orb or dot at rest, never
  a waveform shouting in the corner. It brightens only for an *event* (speech, a name caught), then
  settles.
- Show **which agents are attending** to a sense as faces, the same way the crew strip does. A sense
  is shared by the org, so its UI shows the room, not a lone microphone icon.
- **The orb's own motion** (`VoiceMode.tsx`): the core follows the level on a lively spring (`damping 12,
  stiffness 160`), and its rings follow on a softer one (`damping 14, stiffness 120`). The orb is bouncier
  than a sheet because it is a voice, not furniture. *Thinking* is a slow ring breathe-and-turn, `2.4s` and up
  per ring. *Speaking* is a `1.6s` pulse. Both loop only while that phase lasts.
- **The ear's control** (`observatory/web/src/components/EarControl.tsx`) is the reference for a background
  sense. At rest it is a pill with a small orb and one word. Tapping it opens a sheet with one serif line
  for the state, the attending faces, one action and a footnote saying what is kept and for how long. A name
  caught glows on that agent's face for a few seconds. Muted is warn, offline is grey, and neither shouts.

## 9. Restraint

- One idea per screen, one serif line, one signature-gradient element, one ambient motion (the aurora).
- At most one thing glows at a time. Glow means attention, and attention is scarce.
- Icons are outline only, on a 24px viewBox with `strokeWidth 1.8`, round caps and joins (`I` in `ui.tsx`).
  Don't import an icon font.
- Generous space: `gap-2`–`gap-3` inside controls, `px-4`/`px-5` inside sheets. Let things breathe.
- Never add a new colour, a new font, a new shadow style or a second background effect. If you
  need one, propose it here first.

## 10. Hands and phones

- Icon-only buttons have a `title` and an `aria-label`. Focus is the theme ring
  (`:focus-visible`, accent at 70%), so never remove it.
- Phone: tap targets are `h-11`, and floating sheets are `w-[min(356px,calc(100vw-2rem))]`. Side
  panels become `max-md:fixed … max-md:!w-[92vw]`. Secondary chrome such as the crew strip may
  `hidden sm:flex`. Nothing scrolls sideways.

## Before you ship (check, don't assume)

1. No hex in components, everything is tokens, and it looks right in Astryx **and** a light theme.
2. Every async state has a label, every empty state a promise, and every error a next step.
3. If an agent acts, there is a face, it travels to *where*, and it settles to done and then idle.
4. Motion runs on living states only, is smoothed, and has a still frame under reduced motion.
5. Count the glows and gradients on the screen. More than one is too many.
6. You looked at it at phone width. For canvas pages, `canvas.py preview` and its PNGs. For the
   apps, a real browser.
