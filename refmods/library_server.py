"""
The Refmods web app: Library, Create, Packs and Setup, from refmods/web, and
the endpoints they call. Served by WanGP at WEB_PATH (register_web_app) and
shown on the Refmods tab in a frame, the way the Prompt Builder is.
"""

from __future__ import annotations

import os

from fastapi import Body, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import core, create_service, library_service as lib

WEB_PATH = "/refmods_library"
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


class _NoCache(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def _err(exc, status=400):
    return JSONResponse({"ok": False, "message": str(exc) or exc.__class__.__name__}, status_code=status)


def create_app(plugin, model_lists):
    """model_lists() -> {"h3": [(label, type)], "h3_default": type, "flux": [(label, type)]}.
    The plugin may offer _library_setup(model) and _library_autoarm(turn_off) for the Setup page."""
    jobs = lib.Jobs(plugin)
    app = FastAPI(title="Refmods", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", _NoCache(directory=STATIC), name="static")

    def act(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except FileNotFoundError as exc:
            return _err(f"Not found: {exc}", 404)
        except Exception as exc:                                      # noqa: BLE001
            return _err(exc)

    @app.get("/", response_class=HTMLResponse)
    def index():
        with open(os.path.join(STATIC, "library.html"), "r", encoding="utf-8") as handle:
            page = handle.read()
        version = str(int(max(os.path.getmtime(os.path.join(STATIC, f)) for f in os.listdir(STATIC))))
        return HTMLResponse(page.replace("__V__", version), headers={"Cache-Control": "no-cache"})

    @app.get("/api/session")
    def session():
        from . import flux, flux_ui
        try:
            models = model_lists()
        except Exception as exc:                                      # noqa: BLE001
            models = {"h3": [], "h3_default": None, "flux": [], "error": str(exc)}
        return {"models": models, "concepts": list(core.CONCEPT_TYPES),
                "flux_concepts": list(flux.CONCEPT_TYPES), "budgets": flux_ui.BUDGET_UI,
                "budget_default": flux.DEFAULT_BUDGET, "layouts": flux_ui.LAYOUT_UI,
                "layout_default": flux.LAYOUT_SEPARATE, "session_ready": jobs.session() is not None,
                "roles": list(lib.storage.PACK_ROLES), "kinds": list(lib.storage.PACK_KINDS),
                "enc_default": core.ENC_MAX_EDGE}

    # -- Library ---------------------------------------------------------------------
    @app.get("/api/mods")
    def mods():
        return {"items": lib.list_items(), "folders": lib.folders()}

    @app.get("/api/mod")
    def mod(id: str):
        return act(lib.details, id)

    @app.get("/api/thumb")
    def thumb(id: str, big: int = 0, v: str = ""):
        try:
            data = lib.thumb(id, bool(big))
        except Exception:                                             # noqa: BLE001
            data = None
        if data is None:
            return Response(status_code=404)
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "max-age=60"})

    @app.get("/api/frame")
    def frame(id: str, i: int):
        try:
            data = lib.frame(id, i)
        except Exception:                                             # noqa: BLE001
            data = None
        if data is None:
            return Response(status_code=404)
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "max-age=60"})

    @app.get("/api/output")
    def output(id: str, file: str, strength: int = 0):
        path = lib.output_path(id, file, bool(strength))
        if not path:
            return Response(status_code=404)
        return FileResponse(path, headers={"Cache-Control": "no-cache"})

    @app.post("/api/save")
    def save(payload: dict = Body(...)):
        return act(lib.save, payload.get("id"), payload.get("name"), payload.get("description"),
                   payload.get("concept"))

    @app.post("/api/copy")
    def copy(payload: dict = Body(...)):
        return act(lib.copy, payload.get("id"))

    @app.post("/api/delete")
    def delete(payload: dict = Body(...)):
        return act(lib.delete, payload.get("ids") or [])

    @app.post("/api/move")
    def move(payload: dict = Body(...)):
        return act(lib.move, payload.get("ids") or [], payload.get("destination"))

    @app.post("/api/folder")
    def folder(payload: dict = Body(...)):
        if payload.get("delete"):
            return act(lib.delete_folder, payload.get("model"), payload.get("path"))
        return act(lib.create_folder, payload.get("model"), payload.get("path"))

    @app.post("/api/reclassify")
    def reclassify():
        return act(lib.reclassify)

    @app.post("/api/hint")
    def hint(payload: dict = Body(...)):
        return act(lib.prompt_hint, payload.get("ids") or [])

    @app.post("/api/edit_pictures")
    def edit_pictures(payload: dict = Body(...)):
        return act(lib.edit_pictures, payload.get("id"), payload.get("keep") or [], bool(payload.get("as_copy", True)))

    @app.post("/api/trim_audio")
    def trim_audio(payload: dict = Body(...)):
        return act(lib.trim_audio, payload.get("id"), payload.get("start"), payload.get("end"),
                   bool(payload.get("as_copy", True)), bool(payload.get("remove")))

    @app.post("/api/preview")
    async def preview(request: Request, id: str, clear: int = 0, output: str = "", strength: int = 0):
        try:
            if clear:
                return lib.clear_preview(id)
            if output:
                return lib.set_preview_from_output(id, output, bool(strength))
            return lib.set_preview(id, await request.body())
        except Exception as exc:                                      # noqa: BLE001
            return _err(f"Could not use that picture ({exc}).")

    # -- uploads (Create sources, soundtracks, previews) -----------------------------------
    @app.post("/api/upload")
    async def upload(request: Request, name: str = "file"):
        try:
            path = lib.save_upload(name, await request.body())
            token = os.path.basename(path)
            info = {"ok": True, "token": token}
            try:
                info.update(create_service.probe(token))
            except Exception as exc:                                  # noqa: BLE001
                info["probe_error"] = str(exc)
            return info
        except Exception as exc:                                      # noqa: BLE001
            return _err(exc)

    @app.get("/api/upload")
    def uploaded(token: str):
        path = lib.upload_path(token)
        if not path:
            return Response(status_code=404)
        return FileResponse(path, headers={"Cache-Control": "max-age=600"})

    # -- Create --------------------------------------------------------------------------
    @app.post("/api/estimate")
    def estimate(payload: dict = Body(...)):
        return act(create_service.estimate, payload.get("form") or {}, payload.get("sources") or [])

    @app.post("/api/picture_tool")
    def picture_tool(payload: dict = Body(...)):
        return act(create_service.picture_tool, payload.get("token"), payload.get("op"), payload.get("amount"))

    @app.post("/api/process_video")
    def process_video(payload: dict = Body(...)):
        return act(create_service.process_video, payload.get("token"), payload.get("ops") or [], payload.get("crop"))

    @app.post("/api/cut_audio")
    def cut_audio(payload: dict = Body(...)):
        return act(create_service.cut_audio, payload.get("token"), payload.get("start"), payload.get("end"))

    # -- Packs ---------------------------------------------------------------------------
    @app.get("/api/packs")
    def packs():
        return lib.packs()

    @app.post("/api/packs/save")
    def save_pack(payload: dict = Body(...)):
        return act(lib.save_pack, payload.get("pack") or {}, payload.get("old_name"))

    @app.post("/api/packs/delete")
    def delete_pack(payload: dict = Body(...)):
        return act(lib.delete_pack, payload.get("name"))

    @app.post("/api/packs/add")
    def add_to_pack(payload: dict = Body(...)):
        return act(lib.add_to_pack, payload.get("name"), payload.get("ids") or [], bool(payload.get("new")),
                   payload.get("kind") or "mixed")

    # -- Setup ---------------------------------------------------------------------------
    @app.get("/api/setup")
    def setup(model: str = ""):
        fn = getattr(plugin, "_library_setup", None)
        if not callable(fn):
            return {"lines": ["This build can't check the setup from here."], "autoarm": ""}
        return act(fn, model)

    @app.post("/api/autoarm_off")
    def autoarm_off():
        fn = getattr(plugin, "_library_autoarm_off", None)
        return act(fn) if callable(fn) else _err("not available")

    # -- jobs ----------------------------------------------------------------------------
    @app.post("/api/jobs")
    def start_job(payload: dict = Body(...)):
        return {"id": jobs.start(str(payload.get("op") or ""), payload)}

    @app.get("/api/jobs")
    def active_jobs():
        return {"jobs": jobs.active()}

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        return jobs.status(job_id)

    return app
