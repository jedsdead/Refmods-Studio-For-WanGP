# Changelog

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
