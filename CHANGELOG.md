# Changelog

## [0.2.0] — 2026-11-25

The Prompt Builder, reworked.

- **Reads the Generator page.** The builder sees the start and end images, reference images, reference videos,
  audio references and the source video loaded on the Generator page, and the mods armed in the Refmods panel. It
  loads nothing itself.
- **Modes are picked automatically** (T2VA, I2VA, FL2VA, L2VA, Reference) from what's loaded, with buttons to
  override.
- **Labels.** Everything the generation sends is shown as a label chip, numbered the way the pipeline numbers it
  (start or continued frame, end image, the generation's own references, then mods). Click a chip to insert its
  label where you were typing, in the builder or the prompt box. A dashed chip is sent but not used yet.
- **Subjects with the character creator.** Each subject can take its look from a picture or a mod, or from its
  description only, and its voice from an audio reference, a voice mod, or just gender and tone. Tick which
  features come from the picture; it sets fully or partially preserved. Reference sheets get the one-figure
  sentence. Subjects save to and load from the library.
- **Insert row:** Shot (with its time), Camera (the guide's moves, amplitude and speed), Subject, and a Dialogue row
  with speaker, tone, language and voiceover. Everything follows the bundled H3 guide: subject definitions,
  retention, `<d>[English] ...</d>` lines, speaker IDs in order of who speaks first, no voice types.
- **Enhance** buttons on Action, Sound and Music, each with Undo, and the full writer under the preview.
- **Live preview and checks:** the finished prompt as you type, the guide's format check, labels cited but not sent,
  sent but not used, H3's caps, shot times, dialogue length and the 7,000-character limit.
- **A compact strip under the prompt box** with the detected mode, the label chips and a check of the prompt box.
- Drafts and saved prompts from the 4.x builder load into the new form: the text and subjects come across.
- The old builder is still there as a fallback if the new one fails to start.

## [0.1.0] — 2026-11-25

First version: Refmods For Wan GP `0.38.1-fork.58` and MiniMax H3 Prompt Builder `4.4.0` as two halves of one
plugin, unchanged apart from what the move needed.

- One host plugin loads both halves, each in its own error guard, so one failing to start doesn't take the other
  down. The settings fold at the top of each tab says which half didn't load.
- Refuses to load while Refmods For Wan GP (or g3n3rativ3's original port) or the MiniMax H3 Prompt Builder is
  enabled, with a message in the console and on its tab.
- **Refmods Studio settings** at the top of each tab: turn either half off.
- A one-time copy of Prompt Builder data from a 4.3-or-earlier install. 4.4.0 data is already in
  `loras/h3_prompt_builder/` and is used as it is.
- The builder's tab is now called **Prompt Builder** (was H3 Builder). Its H3 guide and knowledge folder moved
  to the plugin's top level, where WanGP looks for Deepy skills.
- Other plugins that look for Refmods by module still find it: Showrunner Refmods Integration finds the storage
  and patches modules, and 2 Phases Plus finds `PlugIn_Id` and `MiniMaxH3RefModsPlugin` on the plugin module.
