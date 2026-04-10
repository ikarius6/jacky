# Screen Interaction — Technical Deep Dive

Jacky can follow voice or text instructions to **find**, **navigate to**, **click**, **close**, and **minimize** elements on your screen. This document describes the complete flow from user input to physical action.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Intent Detection](#intent-detection)
- [Phase 1: Coarse Grid Locate](#phase-1-coarse-grid-locate)
- [Phase 2: Fine Sub-Grid Locate](#phase-2-fine-sub-grid-locate)
- [Phase 3: Walk & Arrive](#phase-3-walk--arrive)
- [Phase 4: Refine (Optional)](#phase-4-refine-optional)
- [Phase 5: Execute Action](#phase-5-execute-action)
- [Dynamic Crop Sizing](#dynamic-crop-sizing)
- [Coordinate Pipeline](#coordinate-pipeline)
- [Debug Mode](#debug-mode)
- [Configuration & Permissions](#configuration--permissions)
- [Module Map](#module-map)

---

## Overview

When a user says _"haz clic en el botón de Chrome"_ (click the Chrome button), Jacky:

1. **Classifies the intent** — keyword matching or LLM fallback
2. **Captures the full screen** with a numbered grid overlay
3. **Asks the LLM** which grid cell contains the target (Phase 1)
4. **Crops and zooms** into that cell with a finer sub-grid
5. **Asks the LLM again** which sub-cell contains the target (Phase 2)
6. **Walks the pet** to the computed screen coordinates
7. **Optionally refines** with a local 1024×1024 capture (Phase 4)
8. **Executes the action** — click, Alt+F4, or minimize

The entire flow uses **exactly 2 LLM vision calls** in the happy path (grid + sub-grid), with an optional 3rd (refine) when confidence is low.

```
User input
    │
    ▼
┌─────────────────────┐
│   Intent Detection   │  keyword match → fast path
│  (no LLM or 1 call)  │  LLM classify  → fallback
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│  Phase 1: Grid       │  Full screen capture + 8×6 numbered grid
│  (1 LLM vision call) │  → LLM returns cell number + confidence
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│  Phase 2: Sub-Grid   │  Crop around cell + 8×6 sub-grid
│  (1 LLM vision call) │  → LLM returns sub-cell + confidence
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│  Phase 3: Walk       │  Pet runs to target coordinates
└──────────┬──────────┘
           ▼
     confidence ≥ 90?
      ╱          ╲
    YES           NO
     │             │
     ▼             ▼
  Execute    ┌──────────────────┐
     ▲       │  Phase 4: Refine  │  1024×1024 local capture
     │       │  (1 LLM vision)   │  → offset correction
     │       └────────┬─────────┘
     │                │
     └────────────────┘
           ▼
┌─────────────────────┐
│  Phase 5: Execute    │  Click / Alt+F4 / Minimize
└─────────────────────┘
```

---

## Architecture

The screen interaction system is organized as a Python package under `core/screen_interaction/`:

| Module | Responsibility |
|--------|---------------|
| `handler.py` | Main orchestrator — state machine driving all phases |
| `intent_classifier.py` | LLM-based intent classification fallback |
| `task.py` | `ScreenInteractionTask` dataclass — holds state for one task |
| `constants.py` | Shared constants (grid size, thresholds, timeouts) |
| `debug.py` | Debug image helpers — saves intermediate screenshots |

Supporting modules:

| Module | Responsibility |
|--------|---------------|
| `utils/screen_capture.py` | Screen capture, grid overlay drawing, base64 encoding |
| `utils/win32_helpers.py` | Low-level Win32 calls — `click_at`, `send_alt_f4`, `minimize_foreground_window` |
| `core/pet_window.py` | Entry point — wires user input to `ScreenInteractionHandler` |

---

## Intent Detection

User input goes through a **two-tier classification** system:

### Tier 1: Keyword Matching (fast, no LLM)

`handler.try_parse_interaction(text)` checks the input against action keywords defined in `locales/*.json` under `interact_keywords`. Four action types are supported:

| Action | Example keywords (ES) | Example keywords (EN) |
|--------|----------------------|----------------------|
| `navigate` | _encuentra_, _ve hacia_, _camina a_ | _find_, _go to_, _walk to_ |
| `click` | _haz clic_, _presiona_, _pícale a_ | _click_, _press_, _tap_ |
| `close` | _cierra_, _quita_, _mata_ | _close_, _quit_, _kill_ |
| `minimize` | _minimiza_, _esconde_, _achica_ | _minimize_, _hide_, _shrink_ |

Detection priority: **close > minimize > click > navigate** (most destructive first).

After extracting the keyword, prepositional prefixes like _"en el"_, _"a la"_, _"the"_ are stripped using patterns from `interact_prefixes` in the locale file.

### Tier 2: LLM Intent Classification (fallback)

If keyword matching fails, `intent_classifier.classify_intent()` sends the text to the LLM (text-only, no image) to classify it as one of: `click`, `close`, `minimize`, `navigate`, `vision`, or `chat`.

The LLM returns structured JSON:
```json
{"intent": "click", "confidence": 85, "target": "the Chrome icon"}
```

If `confidence ≥ 70` (`INTENT_CONFIDENCE_THRESHOLD`) and the intent is an interaction type, a screen interaction task starts. Otherwise, Jacky treats the input as a general conversation or vision request.

---

## Phase 1: Coarse Grid Locate

**Goal:** Identify which region of the screen contains the target.

**Steps:**

1. **Hide the pet** — The pet window and speech bubble are hidden so they don't appear in the screenshot. A 150ms delay allows Windows to repaint.

2. **Capture the full screen** — `capture_full_screen_gridded()` takes a screenshot of the entire virtual desktop (multi-monitor aware), resizes it to 2048px width (preserving aspect ratio), and overlays a numbered grid.

3. **Grid overlay** — An **8×6 grid** (48 cells) is drawn on the image. Each cell gets a dark circular badge with a white number centered inside it. Grid lines are semi-transparent red.

   ```
   ┌────┬────┬────┬────┬────┬────┬────┬────┐
   │  1 │  2 │  3 │  4 │  5 │  6 │  7 │  8 │
   ├────┼────┼────┼────┼────┼────┼────┼────┤
   │  9 │ 10 │ 11 │ 12 │ 13 │ 14 │ 15 │ 16 │
   ├────┼────┼────┼────┼────┼────┼────┼────┤
   │ 17 │ 18 │ 19 │ 20 │ 21 │ 22 │ 23 │ 24 │
   ├────┼────┼────┼────┼────┼────┼────┼────┤
   │ 25 │ 26 │ 27 │ 28 │ 29 │ 30 │ 31 │ 32 │
   ├────┼────┼────┼────┼────┼────┼────┼────┤
   │ 33 │ 34 │ 35 │ 36 │ 37 │ 38 │ 39 │ 40 │
   ├────┼────┼────┼────┼────┼────┼────┼────┤
   │ 41 │ 42 │ 43 │ 44 │ 45 │ 46 │ 47 │ 48 │
   └────┴────┴────┴────┴────┴────┴────┴────┘
   ```

4. **LLM call** — The gridded image is sent to the LLM as base64 PNG with a prompt asking it to identify the cell closest to the target's center. The LLM responds with:

   ```json
   {"cell": 12, "confidence": 75, "alt_cell": 11}
   ```

   - `cell` — primary candidate cell number
   - `confidence` — 0 to 100 certainty score
   - `alt_cell` — second-best candidate (used for [dynamic crop sizing](#dynamic-crop-sizing))

5. **Compute cell center** — The cell number is converted to pixel coordinates in the resized image space.

---

## Phase 2: Fine Sub-Grid Locate

**Goal:** Pinpoint the exact position within the identified cell region.

**Steps:**

1. **Crop the region** — A region around the identified cell is cropped from the **clean** (un-gridded) screenshot. The crop size is determined by [dynamic crop sizing](#dynamic-crop-sizing) — from 2× to 3× the cell dimensions depending on confidence.

2. **Sub-grid overlay** — An **8×6 sub-grid** (48 sub-cells) is drawn on the cropped image with green grid lines and numbered badges, exactly like Phase 1 but zoomed in.

3. **LLM call** — The zoomed sub-gridded image is sent with a prompt asking the LLM to describe what it sees and identify which sub-cell contains the target's center.

   ```json
   {"cell": 22, "confidence": 88}
   ```

4. **Coordinate mapping** — The sub-cell center is mapped through the coordinate pipeline:
   ```
   sub-cell center → crop-local pixels → resized-image pixels → physical screen pixels → Qt logical coords
   ```

---

## Dynamic Crop Sizing

The crop area for Phase 2 adapts based on Phase 1 confidence and the alternative cell candidate. This solves the common problem of targets sitting on cell boundaries.

### Padding Factor

| Phase 1 Confidence | Padding Factor | Effective Area |
|:---:|:---:|:---|
| `≥ 60` | 2.0× | Standard — covers the cell and half its neighbors |
| `50–59` | 2.5× | Wider — cell might be slightly off |
| `< 50` | 3.0× | Maximum — includes ±1 adjacent cell in each direction |

### Alt-Cell Aware Centering

When the LLM provides an `alt_cell` and confidence is below 80:

1. Check if `alt_cell` is **adjacent** to the primary cell (≤1 cell apart in both axes)
2. Shift the crop center **30% toward the alt candidate** (biased toward the primary)
3. Ensure padding factor is at least **2.5×** to cover both candidates

This guarantees the target element is visible in the Phase 2 crop even if Phase 1 picked the wrong cell by one position.

---

## Phase 3: Walk & Arrive

After Phase 2 computes the target coordinates, the pet **runs** toward the target at 4× normal speed. The pet uses the `RUNNING` animation state if available, otherwise `WALKING`.

On arrival, the handler checks confidence:
- **≥ 90** (the `CONFIDENCE_THRESHOLD`) → skip to Phase 5 (execute)
- **< 90** → proceed to Phase 4 (refine)

---

## Phase 4: Refine (Optional)

**Goal:** Correct any residual positioning error after the pet arrives.

1. **Hide the pet** again
2. **Capture a 1024×1024 area** centered on the pet's current position
3. **Ask the LLM** how far the target is from the image center (in pixels)

   ```json
   {"found": true, "offset_x": -45, "offset_y": 12}
   ```

4. If the offset is > 10px in either axis, adjust the target coordinates and walk again (with confidence boosted to 95 to prevent infinite refinement loops)

---

## Phase 5: Execute Action

After arriving at the final position, Jacky performs the requested action:

| Action | Behavior |
|--------|----------|
| `navigate` | Just arrive — say "done" |
| `click` | Play attack animation (500ms), then `click_at()` via Win32 `SendInput` |
| `close` | Click to bring window to foreground (300ms delay), then `Alt+F4` |
| `minimize` | Click to bring window to foreground (300ms delay), then `ShowWindow(SW_MINIMIZE)` |

### Safety Measures

- **Click-through mode** — The pet window becomes transparent to mouse events during the click so it doesn't click itself (`WS_EX_TRANSPARENT` style)
- **Mouse safety check** — `click_at()` verifies the cursor hasn't moved since the click was initiated (user may have taken over)
- **Timeout** — A 60-second safety timer cancels the entire task if any phase hangs

---

## Coordinate Pipeline

The system navigates four coordinate spaces. Understanding the transformations is critical for debugging:

```
Physical screen (e.g. 3840×2160)
    │  ÷ scale_factor (≈ 1.875)
    ▼
Resized image (2048×1152)
    │  crop_offset + sub-cell calculation
    ▼
Crop-local pixels
    │  + crop_offset → resized coords → × scale_factor
    ▼
Physical screen pixels
    │  ÷ DPI ratio
    ▼
Qt logical coordinates (used for pet.move() and click_at())
```

| Transform | Formula |
|-----------|---------|
| Resized → Physical | `phys = resized × scale_factor` |
| Physical → Qt logical | `qt = phys ÷ dpi_ratio` |
| Qt logical → Physical (for click) | `phys = qt × dpi_ratio` |

---

## Debug Mode

When `debug_logging` is enabled in settings, the handler saves diagnostic images to `debug_screens/` in the config directory:

| File | Content |
|------|---------|
| `00_clean_full.png` | Full screen capture (no grid overlay) |
| `01_grid_sent.png` | Full screen with 8×6 numbered grid (what the LLM sees) |
| `02_grid_result.png` | Grid image with selected cell highlighted in green |
| `03_crop_sent.png` | Cropped region (no sub-grid) |
| `03b_crop_gridded.png` | Cropped region with 8×6 sub-grid overlay |
| `04_crop_result.png` | Crop with crosshair on the located point |
| `05_fullscreen_result.png` | Full screen with crosshair on the final mapped position |

These files are overwritten each interaction, providing a step-by-step visual trace.

---

## Configuration & Permissions

### Required Settings

| Setting | Value | Purpose |
|---------|-------|---------|
| `llm_enabled` | `true` | LLM must be active for vision calls |
| `permissions.allow_vision` | `true` | Required for all interaction types |
| `permissions.allow_screen_interact` | `true` | Required for `click`, `close`, `minimize` (not `navigate`) |

### Constants (`core/screen_interaction/constants.py`)

| Constant | Value | Purpose |
|----------|-------|---------|
| `CONFIDENCE_THRESHOLD` | 90 | Skip refinement if confidence ≥ this |
| `TASK_TIMEOUT_MS` | 60,000 | Safety timeout for the entire task |
| `GRID_COLS` × `GRID_ROWS` | 8 × 6 | Phase 1 grid dimensions |
| `SUB_COLS` × `SUB_ROWS` | 8 × 6 | Phase 2 sub-grid dimensions |
| `INTENT_CONFIDENCE_THRESHOLD` | 70 | Minimum LLM confidence for intent classification |

### Customizable Prompts

All LLM prompts are stored in the locale files (`locales/es.json`, `locales/en.json`) and can be customized per language:

| Key | Phase |
|-----|-------|
| `interact_system_prompt` | System prompt for all vision calls |
| `interact_grid_prompt` | Phase 1 grid identification prompt |
| `interact_locate_prompt` | Phase 2 sub-grid identification prompt |
| `interact_refine_prompt` | Phase 4 refinement prompt |
| `intent_classify_prompt` | Intent classification prompt |

---

## Module Map

```
core/pet_window.py                    ← Entry point: on_ask() / on_listen()
    │
    ├── try_parse_interaction()        ← Tier 1: keyword matching
    │
    ├── classify_intent()              ← Tier 2: LLM intent classification
    │   └── intent_classifier.py
    │
    └── _start_screen_task()
        └── ScreenInteractionHandler   ← core/screen_interaction/handler.py
            │
            ├── _step_capture_and_locate()     Phase 1
            │   └── capture_full_screen_gridded()  ← utils/screen_capture.py
            │
            ├── _on_grid_response()            Parse Phase 1 result
            │
            ├── _step_crop_and_locate()        Phase 2
            │   └── draw_subgrid()             ← utils/screen_capture.py
            │
            ├── _on_locate_response()          Parse Phase 2 result → walk
            │
            ├── on_arrival()                   Phase 3 complete
            │
            ├── _step_refine()                 Phase 4 (optional)
            │   └── capture_vision_area()      ← utils/screen_capture.py
            │
            └── _step_execute()                Phase 5
                └── _do_action()
                    ├── click_at()             ← utils/win32_helpers.py
                    ├── send_alt_f4()          ← utils/win32_helpers.py
                    └── minimize_foreground_window()
```
