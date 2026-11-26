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

The builder reads the Generator page each time you open its tab, so load your references and arm your mods first.
**Check the prompt box** checks whatever is in the Generator page's prompt box.

## Packs

A pack is a set of mods, each with a role: identity, clothing, reference sheet, pose and motion, background, style
or voice. Packs can mix anything. In the **Refmods: MiniMax H3** panel, pick a pack and **Add pack** to put its mods
into the rows, or **Replace all** to start from it. Type a name and **Save as pack** to keep the rows. In the Prompt
Builder, **Draft subjects** turns a character pack into one subject, each mod providing what its role says. Your old
presets are listed as packs.

## The Library

The **Library** subtab of the Refmods tab holds every H3 and Flux mod. Pick a folder or pack on the left, search
and filter at the top, and click a mod to see what's stored in it, rename or move it, edit its description and
concept, or save a copy. Ctrl-click or tick several to move, delete or update them together, or drag them onto a
folder.

What needs the model runs as a short task on the model picked at the top: **Decompile** (the pictures, video and
sound as files), **Strength preview** (the first picture at a few strengths), **Decode to listen** for a voice,
encoder frames, soundtracks, **Clean audio** and **Convert to Flux**. **Replace preview** sets the picture shown
for a mod, from a file or from a decompiled or strength-preview picture. The mod itself doesn't change.

## Installing

1. Put the `Wan2GP-Refmods-Studio` folder in WanGP's `plugins` folder.
2. In **Plugin Manager**, disable **Refmods For Wan GP** and **MiniMax H3 Prompt Builder** if you have them, and
   enable **Refmods Studio**.
3. Restart WanGP.

Refmods Studio won't load while either old plugin is enabled, because the same pipeline hooks would be installed
twice. It says so in the console and on its tab.

## Your data

Nothing needs moving:

- Mods and presets stay in `loras/refmods_plugin/`, as with Refmods For Wan GP. Packs are in its `packs/` folder
  and custom previews in `previews/`.
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
