from __future__ import annotations

import json
from hashlib import sha1
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterable,
    List,
    Optional,
    Tuple,
    TypeVar,
    Union,
    cast,
)
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

import attrs
from lxml.html import (
    FormElement,
    InputElement,
    MultipleSelectOptions,
    SelectElement,
    TextareaElement,
)
from w3lib.encoding import (
    html_body_declared_encoding,
    html_to_unicode,
    http_content_type_encoding,
    read_bom,
    resolve_encoding,
)
from w3lib.html import strip_html5_whitespace
from w3lib.url import canonicalize_url

from web_poet._base import _HttpHeaders
from web_poet.mixins import SelectableMixin, UrlShortcutsMixin
from web_poet.utils import _create_deprecated_class, memoizemethod_noargs

from .url import RequestUrl as _RequestUrl
from .url import ResponseUrl as _ResponseUrl

if TYPE_CHECKING:
    # typing.Self requires Python 3.11
    from typing_extensions import Self

FormdataVType = Union[str, Iterable[str]]
FormdataKVType = Tuple[str, FormdataVType]
FormdataType = Optional[Union[Dict[str, FormdataVType], List[FormdataKVType]]]

T_headers = TypeVar("T_headers", bound=_HttpHeaders)


RequestUrl = _create_deprecated_class("RequestUrl", _RequestUrl)
ResponseUrl = _create_deprecated_class("ResponseUrl", _ResponseUrl)


class HttpRequestBody(bytes):
    """A container for holding the raw HTTP request body in bytes format."""

    pass


class HttpResponseBody(bytes):
    """A container for holding the raw HTTP response body in bytes format."""

    def bom_encoding(self) -> Optional[str]:
        """Returns the encoding from the byte order mark if present."""
        return read_bom(self)[0]

    def declared_encoding(self) -> Optional[str]:
        """Return the encoding specified in meta tags in the html body,
        or ``None`` if no suitable encoding was found"""
        return html_body_declared_encoding(self)

    def json(self) -> Any:
        """
        Deserialize a JSON document to a Python object.
        """
        return json.loads(self)


class HttpRequestHeaders(_HttpHeaders):
    """A container for holding the HTTP request headers.

    It's able to accept instantiation via an Iterable of Tuples:

    >>> pairs = [("Content-Encoding", "gzip"), ("content-length", "648")]
    >>> HttpRequestHeaders(pairs)
    <HttpRequestHeaders('Content-Encoding': 'gzip', 'content-length': '648')>

    It's also accepts a mapping of key-value pairs as well:

    >>> pairs = {"Content-Encoding": "gzip", "content-length": "648"}
    >>> headers = HttpRequestHeaders(pairs)
    >>> headers
    <HttpRequestHeaders('Content-Encoding': 'gzip', 'content-length': '648')>

    Note that this also supports case insensitive header-key lookups:

    >>> headers.get("content-encoding")
    'gzip'
    >>> headers.get("Content-Length")
    '648'

    These are just a few of the functionalities it inherits from
    :class:`multidict.CIMultiDict`. For more info on its other features, read
    the API spec of :class:`multidict.CIMultiDict`.
    """

    pass


class HttpResponseHeaders(_HttpHeaders):
    """A container for holding the HTTP response headers.

    It's able to accept instantiation via an Iterable of Tuples:

    >>> pairs = [("Content-Encoding", "gzip"), ("content-length", "648")]
    >>> HttpResponseHeaders(pairs)
    <HttpResponseHeaders('Content-Encoding': 'gzip', 'content-length': '648')>

    It's also accepts a mapping of key-value pairs as well:

    >>> pairs = {"Content-Encoding": "gzip", "content-length": "648"}
    >>> headers = HttpResponseHeaders(pairs)
    >>> headers
    <HttpResponseHeaders('Content-Encoding': 'gzip', 'content-length': '648')>

    Note that this also supports case insensitive header-key lookups:

    >>> headers.get("content-encoding")
    'gzip'
    >>> headers.get("Content-Length")
    '648'

    These are just a few of the functionalities it inherits from
    :class:`multidict.CIMultiDict`. For more info on its other features, read
    the API spec of :class:`multidict.CIMultiDict`.
    """

    def declared_encoding(self) -> Optional[str]:
        """Return encoding detected from the Content-Type header, or None
        if encoding is not found"""
        content_type = self.get("Content-Type", "")
        return http_content_type_encoding(content_type)


def _is_listlike(x: Any) -> bool:
    """Return ``True`` if *x* is a list-like object, i.e. an iterable but not
    a string or bytes, or ``False`` otherwise."""
    return hasattr(x, "__iter__") and not isinstance(x, (str, bytes))


def _value(
    element: Union[InputElement, SelectElement, TextareaElement]
) -> Tuple[Optional[str], Union[None, str, MultipleSelectOptions]]:
    if element.tag == "select":
        return _select_value(cast(SelectElement, element), element.name, element.value)
    return element.name, element.value


def _select_value(
    element: SelectElement,
    name: Optional[str],
    value: Union[None, str, MultipleSelectOptions],
) -> Tuple[Optional[str], Union[None, str, MultipleSelectOptions]]:
    if value is None and not element.multiple:
        # Match browser behavior on select tags without options
        return (None, None)
    return name, value


def _get_form_query(form: FormElement, data: FormdataType) -> str:
    keys = dict(data or ()).keys()
    if not data:
        data = []
    inputs = form.xpath(
        "descendant::textarea"
        "|descendant::select"
        "|descendant::input[not(@type) or @type["
        ' not(re:test(., "^(?:submit|image|reset)$", "i"))'
        " and (../@checked or"
        '  not(re:test(., "^(?:checkbox|radio)$", "i")))]]',
        namespaces={"re": "http://exslt.org/regular-expressions"},
    )
    values: List[FormdataKVType] = [
        (k, "" if v is None else v)
        for k, v in (_value(e) for e in inputs)
        if k and k not in keys
    ]
    items = data.items() if isinstance(data, dict) else data
    values.extend((k, v) for k, v in items if v is not None)
    encoded_values = [
        (k.encode(), v.encode())
        for k, vs in values
        for v in (cast(Iterable[str], vs) if _is_listlike(vs) else [cast(str, vs)])
    ]
    return urlencode(encoded_values, doseq=True)


def _get_form_method(form: FormElement) -> str:
    method = form.method
    assert method is not None
    method = method.upper()
    if method not in {"GET", "POST"}:
        method = "GET"
    return method


def _get_form_url(form: FormElement) -> str:
    if form.base_url is None:
        raise ValueError(f"{form} has no base_url set.")
    action = form.get("action")
    if action is None:
        return form.base_url
    return urljoin(form.base_url, strip_html5_whitespace(action))


@attrs.define(auto_attribs=False, slots=False, eq=False)
class HttpRequest:
    """Represents a generic HTTP request used by other functionalities in
    **web-poet** like :class:`~.HttpClient`.
    """

    url: _RequestUrl = attrs.field(converter=_RequestUrl)
    method: str = attrs.field(default="GET", kw_only=True)
    headers: HttpRequestHeaders = attrs.field(
        factory=HttpRequestHeaders, converter=HttpRequestHeaders, kw_only=True
    )
    body: HttpRequestBody = attrs.field(
        factory=HttpRequestBody, converter=HttpRequestBody, kw_only=True
    )

    @classmethod
    def from_form(cls, form: FormElement, data: FormdataType = None) -> Self:
        """Return an :class:`HttpRequest` to submit *form* with the
        specified *data*."""
        query = _get_form_query(form, data)
        method = _get_form_method(form)
        url = _get_form_url(form)
        headers = {}
        body = b""
        if method == "GET":
            url = urlunsplit(urlsplit(url)._replace(query=query))
        else:
            assert method == "POST"
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            body = query.encode()
        return cls(
            url=url,
            method=method,
            headers=headers,
            body=body,
        )

    def urljoin(self, url: Union[str, _RequestUrl, _ResponseUrl]) -> _RequestUrl:
        """Return *url* as an absolute URL.

        If *url* is relative, it is made absolute relative to :attr:`url`."""
        return _RequestUrl(urljoin(str(self.url), str(url)))


@attrs.define(auto_attribs=False, slots=False, eq=False)
class HttpResponse(SelectableMixin, UrlShortcutsMixin):
    """A container for the contents of a response, downloaded directly using an
    HTTP client.

    ``url`` should be a URL of the response (after all redirects),
    not a URL of the request, if possible.

    ``body`` contains the raw HTTP response body.

    The following are optional since it would depend on the source of the
    ``HttpResponse`` if these are available or not. For example, the responses
    could simply come off from a local HTML file which doesn't contain ``headers``
    and ``status``.

    ``status`` should represent the int status code of the HTTP response.

    ``headers`` should contain the HTTP response headers.

    ``encoding`` encoding of the response. If None (default), encoding
    is auto-detected from headers and body content.
    """

    url: _ResponseUrl = attrs.field(converter=_ResponseUrl)
    body: HttpResponseBody = attrs.field(converter=HttpResponseBody)
    status: Optional[int] = attrs.field(default=None, kw_only=True)
    headers: HttpResponseHeaders = attrs.field(
        factory=HttpResponseHeaders, converter=HttpResponseHeaders, kw_only=True
    )
    _encoding: Optional[str] = attrs.field(default=None, kw_only=True)

    _DEFAULT_ENCODING = "ascii"
    _cached_text: Optional[str] = None

    @property
    def text(self) -> str:
        """
        Content of the HTTP body, converted to unicode
        using the detected encoding of the response, according
        to the web browser rules (respecting Content-Type header, etc.)
        """
        # Access self.encoding before self._cached_text, because
        # there is a chance self._cached_text would be already populated
        # while detecting the encoding
        encoding = self.encoding
        if self._cached_text is None:
            fake_content_type_header = f"charset={encoding}"
            encoding, text = html_to_unicode(fake_content_type_header, self.body)
            self._cached_text = text
        return self._cached_text

    def _selector_input(self) -> str:
        return self.text

    @property
    def encoding(self) -> Optional[str]:
        """Encoding of the response"""
        return (
            self._encoding
            or self._body_bom_encoding()
            or self._headers_declared_encoding()
            or self._body_declared_encoding()
            or self._body_inferred_encoding()
        )

    @memoizemethod_noargs
    def json(self) -> Any:
        """Deserialize a JSON document to a Python object."""
        return self.body.json()

    @memoizemethod_noargs
    def _body_bom_encoding(self) -> Optional[str]:
        return self.body.bom_encoding()

    @memoizemethod_noargs
    def _headers_declared_encoding(self) -> Optional[str]:
        return self.headers.declared_encoding()

    @memoizemethod_noargs
    def _body_declared_encoding(self) -> Optional[str]:
        return self.body.declared_encoding()

    @memoizemethod_noargs
    def _body_inferred_encoding(self) -> Optional[str]:
        content_type = self.headers.get("Content-Type", "")
        body_encoding, text = html_to_unicode(
            content_type,
            self.body,
            # FIXME: type ignore can be removed when the following is released:
            # https://github.com/scrapy/w3lib/pull/190
            auto_detect_fun=self._auto_detect_fun,  # type: ignore[arg-type]
            default_encoding=self._DEFAULT_ENCODING,
        )
        self._cached_text = text
        return body_encoding

    def _auto_detect_fun(self, body: bytes) -> Optional[str]:
        for enc in (self._DEFAULT_ENCODING, "utf-8", "cp1252"):
            try:
                body.decode(enc)
            except UnicodeError:
                continue
            return resolve_encoding(enc)


def request_fingerprint(req: HttpRequest) -> str:
    """Return the fingerprint of the request."""
    fp = sha1()
    fp.update(req.method.encode() + b"\n")
    fp.update(canonicalize_url(str(req.url)).encode() + b"\n")
    for name, value in sorted(req.headers.items()):
        fp.update(f"{name.title()}:{value}\n".encode())
    fp.update(b"\n")
    fp.update(req.body)
    return fp.hexdigest()
