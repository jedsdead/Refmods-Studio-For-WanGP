"""
The Refmods Library web app: the page in refmods/web and the endpoints it
calls. Served by WanGP at WEB_PATH (register_web_app) and shown in the
Refmods tab in a frame, the way the Prompt Builder is.
"""

from __future__ import annotations

import os

from fastapi import Body, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import core, library_service as lib

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
    """model_lists() -> {"h3": [(label, type)], "h3_default": type, "flux": [(label, type)]}"""
    jobs = lib.Jobs(plugin)
    app = FastAPI(title="Refmods Library", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", _NoCache(directory=STATIC), name="static")

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
                "layout_default": flux.LAYOUT_SEPARATE, "session_ready": jobs.session() is not None}

    @app.get("/api/mods")
    def mods():
        return {"items": lib.list_items(), "folders": lib.folders()}

    @app.get("/api/mod")
    def mod(id: str):
        try:
            return lib.details(id)
        except FileNotFoundError:
            return _err("That mod is no longer there.", 404)
        except Exception as exc:                                      # noqa: BLE001
            return _err(exc)

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
        data = lib.frame(id, i)
        if data is None:
            return Response(status_code=404)
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "max-age=60"})

    @app.get("/api/output")
    def output(id: str, file: str, strength: int = 0):
        path = lib.output_path(id, file, bool(strength))
        if not path:
            return Response(status_code=404)
        return FileResponse(path, headers={"Cache-Control": "no-cache"})

    def act(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:                                      # noqa: BLE001
            return _err(exc)

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

    @app.post("/api/upload")
    async def upload(request: Request, name: str = "file"):
        try:
            path = lib.save_upload(name, await request.body())
            return {"ok": True, "token": os.path.basename(path)}
        except Exception as exc:                                      # noqa: BLE001
            return _err(exc)

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
