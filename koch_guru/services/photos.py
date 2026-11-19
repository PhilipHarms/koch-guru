"""Find photos for recipes that have a link but no cover yet."""

from __future__ import annotations

import asyncio
import logging

import httpx

from koch_guru.services.importer import RecipeImportError, _image, fetch_page, find_jsonld_recipe, page_photo

log = logging.getLogger(__name__)

PAGE_TIMEOUT_SECONDS = 20


async def find_photo(url: str, http: httpx.AsyncClient) -> str | None:
    """The photo of a recipe page: from its recipe data, else the preview photo (og:image)."""
    try:
        final_url, page_html = await asyncio.wait_for(fetch_page(url, http), PAGE_TIMEOUT_SECONDS)
    except (RecipeImportError, TimeoutError, httpx.HTTPError) as exc:
        log.info("Kein Foto von %s: %s", url, exc)
        return None
    data = find_jsonld_recipe(page_html)
    return (_image(data.get("image")) if data else None) or page_photo(page_html, final_url)
