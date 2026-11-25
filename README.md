# Refmods Studio

Refmods and the MiniMax H3 Prompt Builder in one WanGP plugin.

- **Refmods**: no-training reference mods for MiniMax H3 (Ref2VA, FL2VA, FL2VA ControlNet, H3-Image, P-H3-Image)
  and Flux 2 / Flux 3. Compress a reference into a small `.safetensors` file once, then reuse it at any strength
  without re-encoding it every generation.
- **Prompt Builder**: builds MiniMax H3 prompts (T2VA, I2VA, FL2VA, L2VA, Ref2VA) from a form, inline under the
  prompt box and on its own tab, with an optional panel that writes the prompt with WanGP's prompt enhancer and
  Deepy tools for H3 prompts.

The Refmods half is Refmods For Wan GP `0.38.1-fork.58` as it was; its guide is in [`docs/refmods.md`](docs/refmods.md).
The Prompt Builder was reworked in 0.2 (below). The 4.x builder's guide is kept in
[`docs/prompt-builder.md`](docs/prompt-builder.md) for the parts that still apply: the enhancer and the Deepy tools.

## The Prompt Builder

Load your references on the Generator page as usual (start and end images, reference images, videos, audio) and arm
any mods in the Refmods panel. The **Prompt Builder** tab reads them:

- **Mode** is picked from what's loaded, and the buttons override it.
- **What this generation sends** lists every label the pipeline will give, in its order. Click one to insert it
  where you were typing. Dashed means it's sent but not used in the prompt yet.
- **Subjects**: name and describe each one with the character creator, then say where its look comes from (a
  picture, a mod, or the description only) and its voice (an audio reference, a voice mod, or gender and tone). In
  Reference mode they write `subject_definitions` and `retention_analysis` in the bundled H3 guide's wording.
- **Insert**: Shot, Camera, Subject and Dialogue write the guide's notation at the cursor.
- **Enhance** on Action, Sound and Music asks the prompt enhancer set in Configuration to write that box.
- The **live preview** shows the finished prompt, with the checks under it. **Insert into prompt** and **Append
  window** put it in the prompt box.

Under WanGP's prompt box, a compact strip shows the detected mode and the labels, and checks whatever is in the
prompt box.

## Installing

1. Put the `Wan2GP-Refmods-Studio` folder in WanGP's `plugins` folder.
2. In **Plugin Manager**, disable **Refmods For Wan GP** and **MiniMax H3 Prompt Builder** if you have them, and
   enable **Refmods Studio**.
3. Restart WanGP.

Refmods Studio won't load while either old plugin is enabled, because the same pipeline hooks would be installed
twice. It says so in the console and on its tab.

## Your data

Nothing needs moving:

- Mods and presets stay in `loras/refmods_plugin/`, as with Refmods For Wan GP.
- Drafts, saved prompts and saved subjects stay in `loras/h3_prompt_builder/`, as with the Prompt Builder 4.4.0.
  If you're coming from 4.3 or earlier, they're copied in from the old plugin folder the first time Refmods Studio
  starts.
- Refmods Studio's own settings are in `loras/refmods_studio/settings.json`.

## Settings

Each tab has a **Refmods Studio settings** fold at the top. Untick **Refmods** or **Prompt Builder** to hide that
half completely, then restart WanGP. A half that's off isn't loaded at all: turning off Refmods also removes its
pipeline hooks.

## Credits

- **Luisa** ([ComfyUI-MiniMaxH3Mod](https://github.com/Luisacaotica/ComfyUI-MiniMaxH3Mod)): the RefMod idea and
  file format. `refmods/core.py` is a close port of its `core.py` (MIT License, (c) 2026 Luisa/luisacaotica).
- **g3n3rativ3** ([MiniMaxH3Mod-for-WanGP](https://github.com/g3n3rativ3/MiniMaxH3Mod-for-WanGP)): the Wan2GP port
  the Refmods half is built on. See [`docs/refmods.md`](docs/refmods.md) for what came from its later releases.
- **malcolmrey** ([ComfyUI-Flux2Klein9Mod](https://github.com/malcolmamal/ComfyUI-Flux2Klein9Mod)): the Flux 2 /
  Klein RefMod file layout used by the Flux mods.

## License

MIT for the code written for this plugin; see [`LICENSE`](LICENSE). The Refmods half keeps its own terms and
attribution in [`refmods/LICENSE`](refmods/LICENSE), and the Prompt Builder half its MIT licence in
[`builder/LICENSE`](builder/LICENSE).
