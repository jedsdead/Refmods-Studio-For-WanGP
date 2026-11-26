# Changelog

## [0.8.0] — 2026-11-26

Prompt Builder:
- **Tag menu.** Right-click a tag (`<Subject N>`, `<Picture N>`, `<Video N>`, `<Audio N>` or a speaker ID) in a writing
  box to swap it with another or remove it: here, in this box, or everywhere.
  - A subject swapped everywhere takes its subject with it, and one removed everywhere goes from the list, with the
    later subjects moving up.
  - Removing a picture's tag everywhere also takes it off any subject that uses it, so its definition and retention
    lines go.
  - **Undo**, beside the status line, puts it all back.
- Moving or removing a subject card now renumbers its tags in the text too.
- **!Name.** Type `!Jodi` (or `!Jodi Maren`) for a subject; it becomes its tag in the prompt. Tab completes the name.
  A name nobody has is left as typed, with a warning.
- **Phrases**: wording you reuse, with categories and search. Select text and press Ctrl+Enter (or right-click, Save
  as phrase) to keep it; **Phrases** inserts one where you were typing. Kept in `loras/h3_prompt_builder/phrases.json`.
- **Switches.** Each section of the prompt can be switched off above the preview without deleting it, and each
  subject's definition line and retention rows in the subject editor.
- With text selected, right-click also offers Copy, Cut and Remove. Shift+right-click gives the browser's menu.

Refmods:
- **Trim editor:**
  - zoom with − and +, Fit, or the mouse wheel;
  - ← → step a frame (Shift: 10 frames), `[` `]` set in and out, and Home/End jump to them;
  - M mutes, and the readout shows the time from the in point.
- **Use frame** (C) adds the frame at the playhead as a picture, and **Use audio** (A) adds the kept range as an audio
  file. Both are on the Create page.
- **Rotate** and **Mirror** in the crop editor.
- Create won't make a mod that's over **Max tokens**. It used to drop pictures to fit; now it says what to change.

## [0.7.1] — 2026-11-26

- **Full screen**, WanGP's own, as the Video Editor uses it. The button sits at the right of each page's header
  (Refmods and Prompt Builder). In full screen the page fills the window, a Refmods / Prompt Builder switch appears
  beside it, and Esc or the button goes back. `plugin_info.json` declares it (`fullscreen`, `app_url`
  `/refmods-studio`), so WanGP's Apps menu can open Refmods Studio straight in full screen.
- Prompt Builder: the pack picker no longer pushes Load pack onto a second line.

## [0.7.0] — 2026-11-26

- **One Refmods Studio tab.** Refmods and the Prompt Builder are subtabs of it, under one settings fold.
- **Scrub and trim.** A trim editor for videos and audio has a player, a timeline you can click or drag through, in
  and out handles, Set in and Set out at the playhead (I and O), and Play the selection. Sound gets a waveform.
  - On the Create page it's on every video and audio card. A trimmed audio file now starts at its trim, as a
    clip's sound already did, and keeps the trim's length.
  - In the Library, **Choose in and out…** trims a decoded voice or soundtrack.
- **Packs in the Prompt Builder.** A pack can hold a character, with the character creator's fields.
  - **Load pack** arms the pack's mods in the Refmods panel and fills in the subject. Each mod becomes a look source
    providing what its role says (or what was saved with it), and a voice mod becomes the voice.
  - **Save as pack** saves the selected subject's character, its mods and what each one provides.
  - The **Packs** page edits the character too.
- A pack's voice mod is now the subject's voice, rather than a face video's own soundtrack.
- Prompt Builder: only **Time** writes a timestamp. Dialogue lines no longer start with one, and **Shot** writes just
  `[Shot N]`.

## [0.6.0] — 2026-11-26

- **The Refmods tab is one web app** with four pages, Library, Create, Packs and Setup, and one MiniMax H3 model
  picker at the top for every job. The Gradio Extract (H3), Extract (Flux), Decompile, Generate and Auto-arm tabs
  are gone, along with the model picker above them. The panel under the prompt box is unchanged.
- **Create** replaces both Extract tabs, for MiniMax H3 and Flux:
  - drop, choose or paste pictures, videos and an audio file, then drag them into order;
  - crop pictures (free, 1:1, 3:4, 4:3, 9:16, 16:9) and trim videos;
  - one mod from all of them, or one per picture or video;
  - **Full** or **Compressed**, with every old option under **Advanced**;
  - a live estimate of the tokens and file size, with warnings. **Create** stays locked until the mod can be made.
- **Packs** page: edit a pack's mods, roles, strength (0 to 2), how each is sent and its sound, and drag them into
  order. Each mod has an **On** switch: off keeps it in the pack but leaves it out when the pack is added, and the
  Prompt Builder ignores it. Packs also get a subject name for the Prompt Builder and a description.
- **Library** additions:
  - **Add to pack** for one mod or a selection;
  - pack chips that open the pack;
  - **Edit pictures** (drop or reorder a picture mod's pictures) and **Trim** for voices and soundtracks, plus
    **Remove soundtrack**. These cut the stored latents, so nothing is re-encoded.
- **Setup** page: the hook check for the chosen model, what Showrunner, Deepy and API tasks get (with a switch to
  turn it off), and where everything is kept.
- Re-saving a pack from the panel keeps the mods switched off in the editor.

## [0.5.0] — 2026-11-26

- **The Library is a web app**, in the Library subtab of the Refmods tab. It replaces the Library and Decompile
  subtabs and keeps everything they did.
  - Folders and packs on the left, with counts. Make a folder there, delete an empty one, or drag mods onto one to
    move them.
  - Search names, descriptions, concepts and packs. Filter by kind and concept, and sort by name, date, size or
    tokens.
  - Mods are cards with their first stored frame. Badges show the kind, a soundtrack, missing encoder frames and Flux
    mods.
  - The details panel shows the stored frames and what's stored. There you can rename or move a mod, edit its
    description and concept, save a copy, or delete it. Renaming keeps the mod in its packs.
  - Several at once: move, store encoder frames, clean audio, copy a prompt hint, delete.
- **Replace preview**: set the picture shown for a mod, from a file or from a decompiled or strength-preview picture.
  The mod itself doesn't change. Previews are kept in `loras/refmods_plugin/previews/`.
- **Strength preview**: the mod's first picture as the model gets it at three strengths you choose, up to 2.
- **Decode to listen**: a voice or soundtrack decoded and played in the panel.
- Jobs that need the model (decompile, strength preview, encoder frames, soundtracks, clean audio, convert to Flux)
  run as short tasks on the model picked at the top, with their progress shown in the corner.

## [0.4.0] — 2026-11-26

- **Packs.** A pack is a set of mods, each with its role (identity, clothing, reference sheet, pose and motion,
  background, style, voice). The inline panel has a pack row at the top: **Add pack** puts a pack's mods into the
  rows beside what's armed, **Replace all** clears the rows first, **Save as pack** saves the armed rows, and
  **Delete pack** removes one. Packs can be mixed. Mods missing from the folder are skipped and named.
- Presets are now packs. Each saved preset is turned into a pack once; `presets.json` is left where it is.
- The inline panel is compact: one line per mod under a heading row (Mod, Strength, Label, Send as, Sound,
  Soundtrack), still in separate Image, Video and Audio sections. Strength is a number box from 0 to 2.
- The Prompt Builder knows which pack each armed mod came from. **Draft subjects** turns a character pack into one
  subject, with each mod providing what its role says (a face, a costume from a reference sheet, the movement) and
  the pack's voice as the subject's voice. Background and style mods become a location or style subject.
- "voice" is a new concept type, for audio mods and soundtracks.

## [0.3.1] — 2026-11-26

- The live preview scrolls inside its own box, and the checks sit under it instead of being drawn over it in a
  shorter window. The preview panel now stays in view as the form scrolls.

## [0.3.0] — 2026-11-25

The Prompt Builder is now a web app in the Prompt Builder tab, built the way the Video Editor is: its own HTML, CSS
and JavaScript in a frame, served by WanGP, with the Python core behind it doing the labels, the prompt, the checks,
saving and the prompt enhancer.

- Matches the mockups: mode buttons, one toolbar row, label chips with thumbnails, subject cards with the
  character creator underneath, look sources with toggle chips, the insert and line rows, and a live preview with
  the labels, shots and lines highlighted and the checks under it. Follows WanGP's light or dark theme.
- Reads the Generator page each time the tab is opened (WanGP saves the form just before), including the armed
  mods. The note under the labels says when it was read.
- Insert into prompt, Append window and Append as new scene write straight into the Generator page's prompt box,
  and Check the prompt box reads it as it is.
- Location, prop and style subjects show only a name and a description. Look sources show the ones in use plus one
  free row.
- The enhancer runs as a background job with its progress in the status line; Write it all opens in a dialog, with
  Stop.
- **Draft from what's sent** adds a subject for each picture or mod that has none.
- The strip under the prompt box is gone. The Gradio builder from 0.2 stays as the fallback if the web app can't
  start.

## [0.2.4] — 2026-11-25

- **Write [/duration]** beside Length opens the prompt with WanGP's `[/duration=…s]` window command, from the
  Length. **Append as new scene** merges `/new_shot` into it (`[/duration=10s,/new_shot]`) rather than adding a
  second command. Saved with the prompt and the draft.

## [0.2.3] — 2026-11-25

- **Each look source is set on its own.** A subject has up to four sources, each with its own ticks for what it
  provides (face, hair, skin, body type, clothing, movement) and its own reference-sheet box, so `<Video 1>` can give
  the face and `<Picture 1>` the costume. Subject definitions and retention follow each source: a video gets the
  guide's "only her appearance is taken from it" clause, a movement-only source is `transferred`, and the
  description says which features come from which label. A check flags a feature claimed by two sources. Packs
  will fill these rows in later.
- **Summary: Draft from the form** writes who and where from the subjects, and **Enhance** asks the prompt enhancer
  for one or two sentences on the situation, both with Undo.
- Time, Shot, Camera and Insert line always go into the Action box (at its cursor, or at the end). Subject and the
  label chips still go into the writing box last clicked.

## [0.2.2] — 2026-11-25

- Typing in the character creator with no subject yet starts subject 1. Before, nothing happened until **+ New
  subject** (was + Add subject) had been pressed, and nothing said so.
- A **Time** button inserts `At 00:04.000, ` from the *At* box.
- Inserts only go into the builder's writing boxes (Summary, Style, Action, Sound, Music): the one last clicked, or
  Action. Before, they went into whatever box was clicked last, the creator's fields included. The strip's label
  chips always go into WanGP's prompt box.

## [0.2.1] — 2026-11-25

- The format check reads prompts written with section tags (`<subject_definitions>` ... `</subject_definitions>`),
  the H3 guide's default format. Before, every window of such a prompt failed as having no fields.
- It also follows the default format on two points: an `<Audio N>` retention line may end with its speaker ID, and
  a subject whose picture or video has a retention line needs none of its own.
- **Check the prompt box** reads each window's format from the text instead of assuming the detected mode, sums up
  the word counts in one line, and says plainly when labels point at nothing because nothing is loaded or armed.
- Auto picks Reference on a Ref2VA model even with nothing loaded: subjects are then defined by their descriptions.
- Reference mode writes each section between its tags, as the guide's default format does.

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
