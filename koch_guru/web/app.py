"""FastAPI application: login, JSON API and (later) the built front end."""

from __future__ import annotations

import html
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from notion_client import APIErrorCode, APIResponseError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import Scope

from koch_guru.notion_repo import RecipeRepository
from koch_guru.web import api
from koch_guru.web.auth import COOKIE_MAX_AGE, COOKIE_NAME, display_name, user_for_key

log = logging.getLogger(__name__)

Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]

PAGE = """<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KochGuru</title>
<style>
body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#C2501E;color:#FFFFFF;font-family:system-ui,sans-serif;text-align:center;padding:24px;box-sizing:border-box}}
h1{{font-family:Georgia,serif;font-size:40px;margin:0 0 12px}}p{{font-size:17px;margin:0;max-width:320px}}
</style></head><body><main><h1>KochGuru</h1><p>{message}</p></main></body></html>"""


class AppFiles(StaticFiles):
    """The built front end. Unknown paths get index.html, so links like /rezepte work on reload.

    Hashed files under assets/ never change and may be cached for a year; index.html and
    the service worker must always be revalidated so updates reach the phones.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        if path == "api" or path.startswith("api/"):
            raise StarletteHTTPException(status_code=404)
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            response = await super().get_response("index.html", scope)
        if response.status_code == 404:
            response = await super().get_response("index.html", scope)
        if path.startswith("assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif not path.startswith("icons/"):
            response.headers["Cache-Control"] = "no-cache"
        return response


def page(message: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(PAGE.format(message=html.escape(message)), status_code=status_code)


def create_app(
    *,
    repo: RecipeRepository,
    users: dict[str, str],
    lifespan: Lifespan | None = None,
    static_dir: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="KochGuru", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.repo = repo
    app.state.users = users
    if not users:
        log.warning("APP_USERS ist leer: Niemand kann sich in der Web-App anmelden.")

    app.include_router(api.router)

    @app.exception_handler(APIResponseError)
    async def notion_error(request: Request, exc: APIResponseError) -> JSONResponse:
        log.warning("Notion-Fehler bei %s: %s", request.url.path, exc.code)
        if exc.code == APIErrorCode.RateLimited:
            return JSONResponse({"detail": "Notion ist gerade ausgelastet, bitte gleich nochmal."},
                                status_code=503, headers={"Retry-After": "2"})
        return JSONResponse({"detail": "Notion hat die Anfrage abgelehnt."}, status_code=502)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/login/{key}", include_in_schema=False)
    async def login(key: str, request: Request):
        name = user_for_key(request.app.state.users, key)
        if name is None:
            return page("Dieser Anmeldelink ist ungültig oder nicht mehr aktuell.", status_code=404)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            COOKIE_NAME, key, max_age=COOKIE_MAX_AGE, httponly=True,
            secure=request.url.scheme == "https", samesite="lax",
        )
        log.info("Anmeldung: %s", name)
        return response

    @app.get("/logout", include_in_schema=False)
    async def logout():
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie(COOKIE_NAME)
        return response

    if static_dir and (static_dir / "index.html").is_file():
        app.mount("/", AppFiles(directory=static_dir, html=True), name="app")
    else:
        @app.get("/", include_in_schema=False)
        async def placeholder(request: Request):
            name = user_for_key(request.app.state.users, request.cookies.get(COOKIE_NAME))
            if name is None:
                return page("Bitte öffne deinen persönlichen Anmeldelink.", status_code=401)
            return page(f"Hallo {display_name(name)}! Die App ist im Aufbau, die Schnittstelle läuft schon.")

    return app

