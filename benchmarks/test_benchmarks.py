from __future__ import annotations

from typing import TYPE_CHECKING, Any

import attrs
import pytest

from benchmarks.pages import (
    ArticlePage,
    JmesPathArticlePage,
    JobPostingPage,
    JsonLdArticlePage,
    MinimalPage,
    ProductDetailsPage,
    ProductPage,
)
from web_poet import ItemPage

if TYPE_CHECKING:
    import asyncio

    from benchmarks.conftest import PageBuilder

#: Page object class and fixture name of every benchmark, keyed by benchmark
#: name. Results are tracked by name over time, so a name is meant to outlive
#: changes to the page object it measures.
BENCHMARKS: dict[str, tuple[type[ItemPage], str]] = {
    "product_imperative": (ProductPage, "product"),
    "product_details_nodes": (ProductDetailsPage, "product"),
    "article_imperative": (ArticlePage, "article"),
    "article_jsonld": (JsonLdArticlePage, "article"),
    "article_jmespath": (JmesPathArticlePage, "article"),
    "job_imperative": (JobPostingPage, "job"),
    "minimal": (MinimalPage, "minimal"),
}


def _extract(loop: asyncio.AbstractEventLoop, page: PageBuilder, name: str) -> Any:
    page_cls, fixture = BENCHMARKS[name]
    return loop.run_until_complete(page(page_cls, fixture).to_item())


@pytest.mark.parametrize("name", list(BENCHMARKS))
def test_extraction(benchmark, loop, page, name: str) -> None:
    benchmark(_extract, loop, page, name)


@pytest.mark.parametrize("name", list(BENCHMARKS))
def test_every_field_is_extracted(loop, page, name: str) -> None:
    """Guard the benchmarks against measuring extraction that no longer
    extracts anything."""
    item = _extract(loop, page, name)
    empty = [
        field.name
        for field in attrs.fields(type(item))
        if not getattr(item, field.name)
    ]
    assert not empty
