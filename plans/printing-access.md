# Printing access plan

You don't own a printer. Prints go through the Louisville Public Library (Colorado), or a friend's printer when available. Both are occasional, so models are built and checked well ahead, and each is sized for a specific printer before it's sent.

## Louisville Public Library: what the service allows

These details are from the library's 3D printing page and request form, checked on 2026-10-23. Recheck before relying on them.

| Rule | Value |
|---|---|
| How | Online request form with an STL upload; staff print it, and you pick it up. There's no hands-on printer access. |
| Who | Requires a Louisville Library card. |
| Cost | Free, currently. |
| Printers | LulzBot SideKick 747 and LulzBot Mini 2 |
| **Max size** | **152 × 152 × 158 mm** (the Mini 2's print area). The form gives this limit even though the SideKick is bigger. |
| **Max print time** | **8 hours**, in PLA |
| Colours | One colour per print, from whatever filament they have |
| **Quota** | **5 models per month** per person or family |
| Turnaround | Up to 10 days; pick up within 3 business days of notice |
| Review | Custom STLs are reviewed and printed only if approved |
| File | `.stl` only. The form states no file-size limit. |

Request form: https://forms.louisvilleco.gov/Cultural-Services/Library/Request-a-3D-Print

### Questions to ask the library (by phone, 303-335-4849, or at the desk)

1. Can a larger or longer job run on the SideKick 747, which is about 231 × 231 mm, if it's arranged in advance? This decides whether Winter Park can stay at 1 mm = 100 m.
2. Is there a file-size limit on uploads? Terrain STLs can be 30–70 MB.
3. What nozzle and layer height do they use, and what slicer? (LulzBot normally uses Cura LulzBot Edition.) This tells us how to estimate the 8-hour limit.
4. Can you ask for a specific infill, such as 10%? Their page says you can ask for more infill or thicker walls, so less may be possible too.
5. Since this is an accessibility project, would they consider an exception to the 5-per-month quota or the 8-hour limit?
6. Do they reject prints that look unusual, such as a flat plate of test lines? A short note on the request explaining it's a tactile calibration plate should help.

## What this changes in the build

### Printer profiles, not one printer

The user config holds several named printer profiles. Each model chooses one (`print.printer`), and `analyze_model` checks the model against that printer:

```toml
[printers.louisville-library]
bed_mm = [152, 152, 158]
nozzle_mm = 0.5            # to confirm with the library (Mini 2 stock nozzle is 0.5)
max_print_hours = 8
single_color = true
monthly_quota = 5
notes = "Request via library form; up to 10 days; one colour."

[printers.friend]
bed_mm = [0, 0, 0]         # unknown until we ask
nozzle_mm = 0.4
max_print_hours = 0        # 0 = no limit
```

- The bed-fit analyzer uses the selected printer's bed. If a model doesn't fit, it suggests the exact scale that does, as an `update_model` patch.
- **Print-time limit check:** if a slicer CLI is installed, slice with a profile matching the target printer and compare against `max_print_hours`. If none is installed, report "print time unknown; this printer has an 8-hour limit" instead of guessing. Installing PrusaSlicer or OrcaSlicer (both free) is worth it here, so the slicer step moves from Phase 3 to Phase 1 as optional. Check that one of them has a LulzBot Mini 2 printer profile; if not, make a custom one from the Mini 2's specs.
- **STL size:** the 0.2 mm grid gives files of about 50–70 MB. Add a `grid_mm` setting per printer profile (0.25 mm for a 0.5 mm nozzle) and simple decimation of flat areas, so library uploads stay small. Phase 1, M8.
- **Print pack** gains `SUBMIT-NOTES.txt` for the library. It has a two-sentence description for staff ("Tactile terrain map for a blind user; prints flat side down, no supports"), the requested colour (any high-contrast colour, which doesn't matter for touch), and the requested infill.

### Monthly quota planning

Five prints a month at up to 10 days each means printing comes in rounds. The first round:

| # | Print | Fits the library? | Purpose |
|---|---|---|---|
| 1 | Tactile sampler (`standard`) | Yes, at 140 × 120 mm | Decide line sizes and profiles before anything else |
| 2 | Winter Park cirque crop | Yes, ≈ 50 × 50 mm, short | Can the Second Creek cirques be felt? |
| 3 | Winter Park flat | Only at the smaller scale (see below) | Can the line types be told apart without terrain? |
| 4 | Winter Park terrain | Only at the smaller scale, and if under 8 h | The real test |
| 5 | Spare | | A reprint after sampler results, or a dovetail coupon later |

Prints 1 and 2 can go in first, and 3 and 4 once the sampler results have adjusted the line sizes. With a 10-day turnaround, that's two trips.

## Winter Park at the library's size

At 1 mm = 100 m, Winter Park is about 128 × 189 mm, too long for 152 mm. Options:

| Option | Size | Effect |
|---|---|---|
| **A. 1 mm = 125 m** (recommended for the library) | ≈ 102 × 151 mm, ≈ 20 mm tall at 1.5× | Everything shrinks 20%. The cirque crop shows whether that's still readable; at this scale a 1.6 mm river line covers 200 m of ground. |
| B. Crop the north end (drop the town of Fraser) | ≈ 128 × 150 mm at 1 mm = 100 m | Keeps the scale, loses the north part of the valley |
| C. Two tiles | 2 × ≈ 128 × 95 mm | Needs joints (Phase 2), uses two quota slots |
| D. The SideKick, if the library agrees | 128 × 189 mm as planned | Depends on question 1 |
| E. Friend's printer | As planned | Depends on their bed size |

Plan: build both `winter-park` (1 mm = 100 m, for the friend's printer or the SideKick) and `winter-park-library` (option A). They come from the same spec with a different scale and printer, and the cache makes the second build quick.

The 8-hour limit is the bigger risk for the terrain model. A ~20 mm tall solid relief on a slow printer may take longer than 8 hours. Ways to bring it down, in order:

1. low infill (10%)
2. thicker layers (0.3 mm; the vertical detail that matters is around 1 mm)
3. a hollow underside with ribs. This is the "later" option in the packaging plan, moved up if needed.

Only a slicer estimate settles it.

## The friend's printer

Ask them for:

- the printer model
- the bed size
- the nozzle size
- which slicer they use
- whether they're fine with prints of about 4–8 hours

Each print pack carries the filament estimate, so reimbursing them is easy.

## Buying a printer later

The tool doesn't depend on owning one. If you buy one, add its profile to the config. A bed of about 250 mm would fit Winter Park at 1 mm = 100 m, and later fewer tiles for the India and Pakistan model.
