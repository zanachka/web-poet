from __future__ import annotations

import asyncio
import gzip
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from web_poet import HttpResponse, ItemPage

FIXTURES = Path(__file__).parent / "fixtures"

#: Every fixture is served as a real response of its website would be, charset
#: included, so that encoding detection is not part of what is measured.
HEADERS = {"Content-Type": "text/html; charset=utf-8"}

URLS = {
    "product": "https://www.ecommerce.example/dp/B0BENCH001",
    "article": "https://www.news.example/news/articles/b3nchmarkid0",
    "job": "https://www.jobs.example/jobs/view/9000000001",
    "minimal": "https://www.example.com/",
}

MINIMAL_BODY = b"""<html><head><title>Alder Vale</title></head>
<body><h1>Copper Ridge</h1><a href="/aspen">Aspen</a></body></html>"""

PageBuilder = Callable[[type[ItemPage], str], Any]


@pytest.fixture(scope="session")
def loop() -> Iterator[asyncio.AbstractEventLoop]:
    """An event loop reused by every benchmark, so that the cost of creating one
    is not measured over and over."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def bodies() -> dict[str, bytes]:
    bodies = {
        name: gzip.decompress((FIXTURES / f"{name}.html.gz").read_bytes())
        for name in URLS
        if name != "minimal"
    }
    return bodies | {"minimal": MINIMAL_BODY}


def _build(page_cls: type[ItemPage], name: str, bodies: dict[str, bytes]) -> Any:
    response = HttpResponse(URLS[name], body=bodies[name], headers=HEADERS)
    return page_cls(response=response)  # type: ignore[call-arg]


@pytest.fixture(scope="session")
def warm_pages(bodies: dict[str, bytes]) -> PageBuilder:
    pages: dict[tuple[type[ItemPage], str], Any] = {}

    def warm_page(page_cls: type[ItemPage], name: str) -> Any:
        key = (page_cls, name)
        if key not in pages:
            page = _build(page_cls, name, bodies)
            page.selector
            pages[key] = page
        return pages[key]

    return warm_page


@pytest.fixture(params=["cold", "warm"])
def page(
    request: pytest.FixtureRequest,
    bodies: dict[str, bytes],
    warm_pages: PageBuilder,
) -> PageBuilder:
    """Return a function that builds the named page object.

    A cold page object is a new one over a new response, and so it decodes and
    parses the document again on every call, as it does when a spider downloads
    a page. A warm one is reused, and its selector already exists, which leaves
    only the queries and the field machinery to measure.

    A page object parses the response on its own, rather than sharing the
    selector of the response, so reusing the response is not enough to warm
    one up."""
    if request.param == "warm":
        return warm_pages
    return lambda page_cls, name: _build(page_cls, name, bodies)
