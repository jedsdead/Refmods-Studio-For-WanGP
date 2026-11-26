"""
Refmods Studio: Refmods and the MiniMax H3 Prompt Builder as one WanGP plugin.

WanGP loads one plugin class per folder, so this file is a host. It creates
the two halves - refmods/ (reference mods: the pipeline hooks, the Refmods
tab and the inline panels) and builder/ (the prompt builder: the inline panel,
the Prompt Builder tab, the enhancer panel and the Deepy tools) - each inside
its own error guard, and passes WanGP's calls through to them:

- what a half registers in setup_ui (tabs, component and global requests,
  insert_after panels, data hooks, Deepy tools, custom settings, custom JS)
  is gathered onto the host, which is what WanGP reads;
- what WanGP hands back (the requested components, the globals, the
  set_global function, the API session) is forwarded to every half;
- post_ui_setup, on_model_change and the tab events are forwarded too.

A half that fails to start is left out and the other still loads. The whole
plugin refuses to load while the old Refmods or Prompt Builder plugin is
enabled: pipeline hooks installed twice break generation.
"""

import json
import os
import shutil
import sys
import traceback
from pathlib import Path

import gradio as gr

from shared.utils.plugins import WAN2GPPlugin

PLUGIN_NAME = "Refmods Studio"
PLUGIN_VERSION = "0.8.2"

# Kept on this module so other plugins that look for Refmods by these names
# still find it here: 2 Phases Plus checks the plugin module of an enabled
# plugin for PlugIn_Id and a MiniMaxH3RefModsPlugin attribute.
# MiniMaxH3RefModsPlugin is only added once the Refmods half has loaded, so a
# plugin checking for it doesn't find one that isn't there.
PlugIn_Id = "H3RefMods"
NONE_CHOICE = "(none)"
WINDOW_MODE_DEFAULT = "still"

HALVES = ("refmods", "builder")
HALF_LABELS = {"refmods": "Refmods", "builder": "Prompt Builder"}

# Folder names and code markers of the old plugins. A marker catches a clone
# under another folder name, including g3n3rativ3's original port, which
# installs the same hooks.
OLD_PLUGINS = {
    "refmods": {"folders": ("Refmod-Fork", "MiniMaxH3Mod-for-WanGP"),
                "markers": ('PlugIn_Id = "H3RefMods"',),
                "label": "Refmods For Wan GP (Refmod-Fork)"},
    "builder": {"folders": ("Wan2GP-Minimax-H3-Prompt-Builder",),
                "markers": ("class H3PromptBuilderPlugin(",),
                "label": "MiniMax H3 Prompt Builder"},
}

HERE = Path(__file__).resolve().parent

# Attributes WanGP sets on the plugin that the halves need on themselves.
# Requested components and globals are added to this as the halves ask.
_ALWAYS_FORWARD = {"_set_wgp_global_func", "goto_media_tab", "_wangp_session"}


# -- settings -----------------------------------------------------------------

def _wangp_root():
    for folder in HERE.parents:
        if (folder / "wgp.py").is_file():
            return folder
    return Path.cwd()


def _data_dir():
    """loras/refmods_studio: this plugin's own settings, beside the halves' data."""
    path = _wangp_root() / "loras" / "refmods_studio"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:                                 # noqa: BLE001
        pass
    return path


def _settings_path():
    return _data_dir() / "settings.json"


def read_settings():
    try:
        data = json.loads(_settings_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:                                 # noqa: BLE001
        return {}


def write_settings(data):
    path = _settings_path()
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temp.replace(path)


def half_enabled(settings, half):
    return settings.get(f"show_{half}", True) is not False


# -- the old plugins ------------------------------------------------------------

def _wgp_config():
    """WanGP's config: the running one when it can be found, else the file."""
    for name in ("wgp", "__main__"):
        mod = sys.modules.get(name)
        cfg = getattr(mod, "server_config", None) if mod is not None else None
        if isinstance(cfg, dict):
            return cfg
    for filename in ("wgp_config.json", "server_config.json"):
        path = _wangp_root() / filename
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:                             # noqa: BLE001
            continue
    return {}


def old_plugins_enabled():
    """The old plugins that are enabled, as display labels."""
    enabled = _wgp_config().get("enabled_plugins") or []
    plugins_dir = HERE.parent
    found = []
    for folder in enabled:
        if folder == HERE.name:
            continue
        code = ""
        try:
            code = (plugins_dir / folder / "plugin.py").read_text(
                encoding="utf-8", errors="ignore")
        except Exception:                             # noqa: BLE001
            pass
        for info in OLD_PLUGINS.values():
            if folder in info["folders"] or any(m in code for m in info["markers"]):
                found.append(f"{info['label']} (folder `{folder}`)")
                break
    return found


def import_old_builder_data():
    """
    Copy a 4.3-or-earlier Prompt Builder's data in, once.

    The Prompt Builder 4.4.0 keeps drafts, prompts and subjects in
    loras/h3_prompt_builder, which the builder half here uses too, so an
    up-to-date install needs nothing. An older one kept them in its own plugin
    folder; those are copied (not moved - the old plugin is not ours to empty)
    and nothing already in place is overwritten. The enhancer settings and the
    cast folder come across the same way.
    """
    settings = read_settings()
    if settings.get("imported_builder_data"):
        return
    old = HERE.parent / OLD_PLUGINS["builder"]["folders"][0]
    copied = 0
    if old.is_dir():
        data = _wangp_root() / "loras" / "h3_prompt_builder"
        pairs = [(old / name, data / name)
                 for name in ("h3_draft.json", "h3_draft.prev.json")]
        for folder in ("prompts", "subjects"):
            if (old / folder).is_dir():
                pairs += [(src, data / folder / src.name)
                          for src in (old / folder).glob("*.json")]
        pairs.append((old / "settings.json", HERE / "settings.json"))
        if (old / "cast").is_dir():
            pairs += [(src, HERE / "cast" / src.name)
                      for src in (old / "cast").glob("*.json")]
        for src, dest in pairs:
            if not src.is_file() or dest.exists():
                continue
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                copied += 1
            except Exception as exc:                  # noqa: BLE001
                print(f"[{PLUGIN_NAME}] could not copy {src}: {exc!r}")
    if copied:
        print(f"[{PLUGIN_NAME}] copied {copied} file(s) of Prompt Builder "
              f"data from {old}")
    settings["imported_builder_data"] = True
    try:
        write_settings(settings)
    except Exception as exc:                          # noqa: BLE001
        print(f"[{PLUGIN_NAME}] could not save its settings: {exc!r}")


# -- the halves -------------------------------------------------------------------

def _load_half(half):
    """Import a half's module and create its plugin object."""
    if half == "refmods":
        from .refmods import plugin as module
        return module, module.MiniMaxH3RefModsPlugin()
    from .builder import plugin as module
    return module, module.H3PromptBuilderPlugin()


class _ClassRef:
    """
    Stands in for the Refmods plugin class on this module.

    An instance rather than the class itself: WanGP takes the first plugin
    class it finds in this file, and that has to be the host.
    """

    def __init__(self, cls):
        self._cls = cls

    def __getattr__(self, name):
        return getattr(self._cls, name)


class RefmodsStudioPlugin(WAN2GPPlugin):
    """The host: creates both halves and passes WanGP's calls through."""

    def __init__(self):
        self._rs_halves = {}           # half -> plugin object
        self._rs_errors = {}           # half -> sentence for the settings panel
        self._rs_forward = set(_ALWAYS_FORWARD)
        self._rs_subtabs = []          # (label, constructor, half): the halves' tabs, as subtabs
        self._rs_blocked = []
        super().__init__()
        self.name = PLUGIN_NAME
        self.version = PLUGIN_VERSION
        self.description = ("Refmods and the MiniMax H3 Prompt Builder in one "
                            "plugin.")

        self._rs_blocked = old_plugins_enabled()
        if self._rs_blocked:
            print(f"[{PLUGIN_NAME}] not loading: disable "
                  + " and ".join(self._rs_blocked)
                  + " in Plugin Manager and restart WanGP. Running both would "
                    "install the same pipeline hooks twice.")
            return

        try:
            import_old_builder_data()
        except Exception as exc:                      # noqa: BLE001
            print(f"[{PLUGIN_NAME}] could not import old Prompt Builder data: "
                  f"{exc!r}")

        settings = read_settings()
        for half in HALVES:
            if not half_enabled(settings, half):
                print(f"[{PLUGIN_NAME}] {HALF_LABELS[half]} is turned off in "
                      "the settings")
                continue
            try:
                module, plugin = _load_half(half)
                self._rs_halves[half] = plugin
                if half == "refmods":
                    globals()["MiniMaxH3RefModsPlugin"] = _ClassRef(
                        module.MiniMaxH3RefModsPlugin)
                    globals()["NONE_CHOICE"] = getattr(module, "NONE_CHOICE",
                                                       NONE_CHOICE)
                    patches = sys.modules.get(f"{__package__}.refmods.patches")
                    globals()["WINDOW_MODE_DEFAULT"] = getattr(
                        patches, "WINDOW_MODE_DEFAULT", WINDOW_MODE_DEFAULT)
            except Exception as exc:                  # noqa: BLE001
                self._rs_fail(half, "could not start", exc)

    # -- forwarding ---------------------------------------------------------

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)
        if name in self.__dict__.get("_rs_forward", ()):
            for plugin in self.__dict__.get("_rs_halves", {}).values():
                try:
                    setattr(plugin, name, value)
                except Exception:                     # noqa: BLE001
                    pass

    def _rs_fail(self, half, what, exc):
        self._rs_halves.pop(half, None)
        self._rs_errors[half] = f"{what}: {type(exc).__name__}: {exc}"
        print(f"[{PLUGIN_NAME}] {HALF_LABELS[half]} {what}: {exc!r}")
        traceback.print_exc()

    def _rs_each(self, method, *args):
        """Call a method on every half that overrides it; returns the results."""
        results = []
        for half, plugin in list(self._rs_halves.items()):
            own = getattr(type(plugin), method, None)
            if own is None or own is getattr(WAN2GPPlugin, method, None):
                continue
            try:
                results.append(getattr(plugin, method)(*args))
            except Exception as exc:                  # noqa: BLE001
                print(f"[{PLUGIN_NAME}] {HALF_LABELS[half]} failed in "
                      f"{method}: {exc!r}")
                traceback.print_exc()
        return results

    # -- lifecycle ----------------------------------------------------------

    def setup_ui(self):
        if self._rs_blocked:
            self.add_tab(tab_id="refmods_studio", label=PLUGIN_NAME,
                         component_constructor=self._rs_blocked_ui)
            return

        for half, plugin in list(self._rs_halves.items()):
            try:
                plugin.setup_ui()
            except Exception as exc:                  # noqa: BLE001
                self._rs_fail(half, "could not set up its interface", exc)

        for half, plugin in self._rs_halves.items():
            self._rs_gather(half, plugin)

        # One Refmods Studio tab, with each half's tab as a subtab.
        if self._rs_subtabs:
            self.add_tab(tab_id="refmods_studio", label=PLUGIN_NAME, component_constructor=self._rs_studio_ui)

        if not self._rs_halves:
            self.add_tab(tab_id="refmods_studio", label=PLUGIN_NAME,
                         component_constructor=self._rs_settings_ui)

    def _rs_gather(self, half, plugin):
        """Move what a half registered onto the host, where WanGP reads it."""
        for comp in plugin.component_requests:
            self.request_component(comp)
            self._rs_forward.add(comp)
        for name in plugin.global_requests:
            self.request_global(name)
            self._rs_forward.add(name)
        for tab_id, tab in plugin.tabs.items():
            self._rs_subtabs.append((tab.label, tab.component_constructor, half))
        self._insert_after_requests.extend(plugin._insert_after_requests)
        plugin._insert_after_requests.clear()
        for hook, callbacks in plugin._data_hooks.items():
            self._data_hooks.setdefault(hook, []).extend(callbacks)
        self._custom_js_snippets.extend(plugin._custom_js_snippets)
        self._deepy_prime_tools.extend(plugin._deepy_prime_tools)
        self._deepy_zero_tools.extend(plugin._deepy_zero_tools)
        self._web_apps.extend(plugin._web_apps)
        self._custom_settings.extend(plugin._custom_settings)
        if plugin._deepy_toolbox is not None and self._deepy_toolbox is None:
            self._deepy_toolbox = plugin._deepy_toolbox

    @staticmethod
    def _rs_takes_api(constructor):
        import inspect
        try:
            params = [p for p in inspect.signature(constructor).parameters.values()
                      if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
            return len(params) >= 1
        except (TypeError, ValueError):
            return False

    def _rs_studio_ui(self, api_session=None):
        """The Refmods Studio tab: the settings fold, then a subtab per half (Refmods, Prompt Builder)."""
        # Each page shows WanGP's Full Screen button in its own header (see the pages' fullscreen code),
        # so WanGP hides its bar; the frames make room for the settings fold and the subtab bar.
        gr.HTML("<style>.rs-studio-tabs .wangp-addon-web-view iframe { height: calc(100vh - 205px) !important; }</style>",
                padding=False)
        self._rs_settings_ui(folded=True)
        with gr.Tabs(elem_classes="rs-studio-tabs"):
            for label, constructor, half in self._rs_subtabs:
                with gr.Tab(label):
                    try:
                        if self._rs_takes_api(constructor):
                            constructor(api_session)
                        else:
                            constructor()
                    except Exception as exc:          # noqa: BLE001
                        self._rs_fail(half, f"could not build its {label} tab", exc)
                        gr.Markdown(f"⚠️ The {label} tab could not be built: `{exc!r}`. The console has the details.")

    def post_ui_setup(self, components):
        updates = {}
        for result in self._rs_each("post_ui_setup", components):
            if isinstance(result, dict):
                updates.update(result)
        return updates

    def on_model_change(self, state, model_type):
        self._rs_each("on_model_change", state, model_type)

    def on_tab_select(self, state):
        """Opening the Refmods Studio tab: each half hears it (the Prompt Builder reads the Generator page)."""
        result = None
        for plugin in self._rs_halves.values():
            if type(plugin).on_tab_select is not WAN2GPPlugin.on_tab_select:
                try:
                    result = plugin.on_tab_select(state) or result
                except Exception as exc:              # noqa: BLE001
                    print(f"[{PLUGIN_NAME}] on_tab_select failed: {exc!r}")
        return result

    def on_tab_deselect(self, state):
        for plugin in self._rs_halves.values():
            if type(plugin).on_tab_deselect is not WAN2GPPlugin.on_tab_deselect:
                try:
                    plugin.on_tab_deselect(state)
                except Exception as exc:              # noqa: BLE001
                    print(f"[{PLUGIN_NAME}] on_tab_deselect failed: {exc!r}")

    # -- UI -----------------------------------------------------------------

    def _rs_blocked_ui(self):
        gr.Markdown(
            f"### {PLUGIN_NAME} is not loaded\n\n"
            "These older plugins are enabled:\n\n"
            + "\n".join(f"- {label}" for label in self._rs_blocked)
            + "\n\nRefmods Studio replaces them, and running both would "
              "install the same pipeline hooks twice. Disable them in "
              "**Plugin Manager** and restart WanGP. Your mods, presets, "
              "prompts and subjects are kept in `loras/` and carry over.")

    def _rs_settings_ui(self, folded=False):
        settings = read_settings()
        wrapper = (gr.Accordion(f"{PLUGIN_NAME} settings", open=False)
                   if folded else gr.Column())
        with wrapper:
            gr.Markdown(f"{PLUGIN_NAME} {PLUGIN_VERSION}. Turn either half "
                        "off to hide it completely. A half that's off isn't "
                        "loaded at all, so turning off Refmods also removes "
                        "its pipeline hooks. **Restart WanGP** after "
                        "saving.")
            problems = [f"**{HALF_LABELS[h]}** {msg}"
                        for h, msg in self._rs_errors.items()]
            if problems:
                gr.Markdown("Not loaded this session: " + "; ".join(problems)
                            + ". The console has the details.")
            with gr.Row():
                show_refmods = gr.Checkbox(
                    label="Refmods", value=half_enabled(settings, "refmods"))
                show_builder = gr.Checkbox(
                    label="Prompt Builder",
                    value=half_enabled(settings, "builder"))
                save = gr.Button("Save", size="sm")
            status = gr.Markdown("")
        save.click(fn=self._rs_save_settings,
                   inputs=[show_refmods, show_builder], outputs=[status])

    @staticmethod
    def _rs_save_settings(show_refmods, show_builder):
        settings = read_settings()
        settings["show_refmods"] = bool(show_refmods)
        settings["show_builder"] = bool(show_builder)
        try:
            write_settings(settings)
        except Exception as exc:                      # noqa: BLE001
            return f"Could not save ({type(exc).__name__}): `{_settings_path()}`."
        if not (show_refmods or show_builder):
            return ("Saved. Both halves are off: after a restart only this "
                    "settings tab is left.")
        return "Saved. Restart WanGP for it to take effect."
