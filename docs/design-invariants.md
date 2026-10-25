# Design invariants

These are deliberate decisions, kept explicit so that a later refactor or "simplification" doesn't quietly undo them. Copy this section into the repo as `docs/design-invariants.md`, and point to it from `CONTRIBUTING.md` and from comments at the relevant code.

1. **Tactile parameters are per person, never hard-coded.**
   - *Why:* tactile sensitivity varies widely, and the people most affected are the people this tool is for. Diabetic neuropathy is common among blind people, because diabetes is a leading cause of blindness. Age, calluses, other neuropathies, and plain biological variation all reduce what a fingertip can resolve. A single tuned default works only for whoever tuned it, and silently excludes everyone else.
   - *Rule:* every line width, line height, spacing, texture amplitude, relief threshold and label size comes from the active tactile profile.
   - *Enforce with a test:* the analyzers and style code must not contain hard-coded numeric tactile thresholds. Search the code for them, or require all of them to come through the profile object.
2. **The sampler and calibration flow is a core feature, not a developer tool.**
   - *Why:* it's the only way a user can find their own limits. Without it, the profiles in invariant 1 are just guesses.
   - *Rule:* don't remove it, don't move it behind a developer flag, and don't reduce it to detecting single samples. The plate must test whether two samples can be told apart.
3. **Sample and tile IDs must not depend on reading Braille.**
   - *Why:* many blind people don't read Braille. Reduced sensitivity can make fine Braille unreadable even for people who do.
   - *Rule:* always include a non-Braille ID, such as counted notches or large raised numerals. Braille is optional and in addition.
4. **Every output must be fully usable as text.**
   - *Why:* the primary users can't see renders. A feature that only shows up in an image doesn't exist for them.
   - *Rule:* every tool returns structured text, and `describe_model` covers every feature, region, warp and legend entry. Images are optional, for model context only.
5. **Distortion is always disclosed.**
   - *Why:* a squished or exaggerated map that doesn't say so teaches false geography.
   - *Rule:* every warp and every regional z scale carries a texture by default, and is reported by `describe_model` with its actual ratios.
6. **Profiles never collect health information.**
   - *Why:* it's not needed, and it's sensitive.
   - *Rule:* profiles hold only numbers and choices. Presets are named by sensitivity level, never by medical condition.
