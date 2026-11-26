"""
The Prompt Builder web app: the page in builder/web and the endpoints it
calls. Served by WanGP at WEB_PATH (register_web_app) and shown in the
Prompt Builder tab in a frame, the way the Video Editor is.
"""

from __future__ import annotations

import os

from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import studio_core as core
from .studio_service import Service

WEB_PATH = "/refmods_studio"
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


class _NoCache(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(plugin, host):
    service = Service(plugin, host)
    app = FastAPI(title="Refmods Studio", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", _NoCache(directory=STATIC), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index():
        with open(os.path.join(STATIC, "index.html"), "r", encoding="utf-8") as handle:
            page = handle.read()
        version = str(int(max(os.path.getmtime(os.path.join(STATIC, f)) for f in os.listdir(STATIC))))
        return HTMLResponse(page.replace("__V__", version), headers={"Cache-Control": "no-cache"})

    @app.get("/api/session")
    def session():
        snap = host.snapshot()
        snap["lists"] = {"prompts": service.prompt_names(), "subjects": service.subject_names()}
        snap["vocab"] = {"modes": list(core.MODES), "kinds": list(core.KINDS), "genders": list(core.GENDERS),
                         "parts": list(core.PARTS), "default_parts": list(core.DEFAULT_PARTS),
                         "languages": list(core.LANGUAGES), "camera": list(core.CAMERA_MOVES),
                         "amplitudes": list(core.AMPLITUDES), "speeds": list(core.SPEEDS),
                         "framings": list(core.FRAMINGS), "rigs": list(core.RIGS), "lenses": list(core.LENSES),
                         "cuts": list(core.CUT_VERBS), "continues": list(core.CONTINUE_VERBS),
                         "bodies": list(core.CAMERA_BODIES),
                         "max_looks": core.MAX_LOOKS}
        return snap

    @app.get("/api/thumb/{key:path}")
    def thumb(key: str):
        data = host.thumbnail(key)
        if data is None:
            return Response(status_code=404)
        return Response(data, media_type="image/png", headers={"Cache-Control": "no-cache"})

    @app.post("/api/preview")
    def preview(payload: dict = Body(...)):
        return service.preview(payload.get("form") or {})

    @app.post("/api/snippet")
    def snippet(payload: dict = Body(...)):
        return {"text": service.snippet(payload.get("kind"), payload.get("form") or {}, payload.get("args") or {})}

    @app.post("/api/check")
    def check(payload: dict = Body(...)):
        return service.check_prompt(payload.get("text") or "")

    @app.post("/api/draft_subjects")
    def draft_subjects(payload: dict = Body(...)):
        return service.draft_subjects(payload.get("form") or {})

    @app.get("/api/prompts")
    def prompts():
        return {"names": service.prompt_names()}

    @app.get("/api/prompts/{name}")
    def load_prompt(name: str):
        return service.load_prompt(name)

    @app.post("/api/prompts")
    def save_prompt(payload: dict = Body(...)):
        return service.save_prompt(payload.get("name"), payload.get("form") or {})

    @app.get("/api/draft")
    def load_draft():
        return service.load_draft()

    @app.post("/api/draft")
    def save_draft(payload: dict = Body(...)):
        return service.save_draft(payload.get("form") or {})

    @app.get("/api/subjects")
    def subjects():
        return {"names": service.subject_names()}

    @app.get("/api/subjects/{name}")
    def load_subject(name: str):
        return service.load_subject(name)

    @app.post("/api/subjects")
    def save_subject(payload: dict = Body(...)):
        return service.save_subject(payload.get("subject") or {})

    @app.get("/api/phrases")
    def phrases():
        return {"phrases": service.phrases()}

    @app.post("/api/phrases")
    def save_phrase(payload: dict = Body(...)):
        return service.save_phrase(payload.get("text"), payload.get("category"), payload.get("id"))

    @app.post("/api/phrases/delete")
    def delete_phrase(payload: dict = Body(...)):
        return service.delete_phrase(payload.get("id"))

    @app.get("/api/packs")
    def packs():
        return {"packs": service.pack_list()}

    @app.post("/api/pack/load")
    def load_pack(payload: dict = Body(...)):
        return service.load_pack(payload.get("name"), payload.get("form") or {})

    @app.post("/api/pack/save")
    def save_pack(payload: dict = Body(...)):
        return service.save_pack(payload.get("name"), payload.get("subject") or {})

    @app.post("/api/jobs")
    def start_job(payload: dict = Body(...)):
        kind = "write" if payload.get("kind") == "write" else "enhance"
        return {"id": service.start_job(kind, payload)}

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        return JSONResponse(service.job_status(job_id))

    @app.post("/api/jobs/{job_id}/stop")
    def stop(job_id: str):
        return service.stop_job(job_id)

    return app
