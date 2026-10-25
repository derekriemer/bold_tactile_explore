---
name: tactile-terrain
description: Build, edit, describe and check 3D-printable tactile terrain models and tactile sampler plates with the tactile-terrain MCP tools. Use when the user wants a tactile or 3D-printed map, terrain model, relief model, or touch-readable map of a place, wants to change one (exaggeration, crop, features, line sizes), wants to know what a model contains, or wants to calibrate their tactile profile with a sampler.
---

# Tactile terrain

The user may be blind and using a screen reader. Everything you report must be complete as text.
Never refer to images, previews, colours or "as you can see". Use headings and short lines; put
units on every number; give positions as mm from the south-west corner, north is the far edge.

## Workflow for a new model

1. `list_capabilities` if you haven't this session, to learn the provider, style and preset names.
2. `resolve_area` with the place or bbox. Read back the area in km, elevation range, and the
   feature counts, including named streams and lifts, so the user can spot missing or wrong data.
3. Confirm the build parameters back to the user in ONE line (area, scale, exaggeration, base,
   mode, feature filters, tactile profile) and wait for a yes or changes.
4. `create_model`. Report the analysis it returns: warnings first, each with its proposed fix.
5. Always `describe_model` and give the user its full text, lightly organised. Don't summarise
   away line courses, crossings or cross-sections; they are the map.
6. `check_print` before calling the model done. Report the file paths.

## Editing

Use `update_model` with the smallest change. Say what changed in before → after form, then run
`describe_model` again if anything the user can feel changed, and `check_print`.
If `analyze_model` attaches a fix, offer it; apply it only when the user agrees.
Every edit keeps the previous spec, so "undo that" is `update_model` with `revert_to`.

## Defaults and rules of thumb

- Take printer, units and tactile profile from the user's config; don't invent sizes.
- Never put tactile sizes in your own words as fixed rules; they come from the user's profile.
- Vertical exaggeration: about 1–1.5× for mountains, about 3× for plains or gentle terrain. Let
  the relief analyzer's suggestion win if it disagrees.
- Creeks: filter by stream order and add named exceptions rather than lowering the cutoff.
- If the user hasn't printed a sampler yet, suggest `create_sampler` before a big print.
- If a tool says a data service could not be reached, tell the user plainly and offer to retry;
  `doctor` shows which services are reachable.

## Sampler

`create_sampler` then `describe_model` on it, and read out every row. The readout reveals which
pairs are identical, so suggest the user feels the plate first and writes down what they could
and could not tell apart before hearing the details. Ask them to report results by row and
sample number. In this version, turn their results into suggested profile edits and show them;
there is no automatic calibration yet. A sampler plate cannot be edited; make a new one.
