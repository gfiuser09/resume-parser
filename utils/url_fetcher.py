"""Fetches a URL supplied by the caller and returns its visible text.

Unlike every other route in this app, the endpoint built on this module makes
the server act as an HTTP client on the caller's behalf - the classic SSRF
shape. Guards here: only http/https, resolve the host and reject
private/loopback/link-local/reserved addresses (blocks cloud metadata
endpoints and internal services too), re-validate every redirect hop (not
just the original URL, since a redirect can point somewhere the first check
never saw), and cap the response size.
"""

import gzip
import ipaddress
import socket
import zlib
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from utils.errors import InvalidURL, URLFetchError

USER_AGENT = "Mozilla/5.0"
FETCH_TIMEOUT_SECONDS = 8
MAX_RESPONSE_BYTES = 5 * 1024 * 1024


class _FastText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg"):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.parts.append(data.strip())


def _ensure_public_host(hostname):
    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise InvalidURL(f"Could not resolve host: {hostname}") from exc

    for *_, sockaddr in addrinfo:
        ip = ipaddress.ip_address(sockaddr[0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise InvalidURL(f"URL resolves to a disallowed address: {sockaddr[0]}")


def _validate_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise InvalidURL("URL must use http or https")
    if not parsed.hostname:
        raise InvalidURL("URL must include a host")
    _ensure_public_host(parsed.hostname)
    return parsed


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_url_text(url):
    """Fetch *url* and return its visible (script/style-stripped) text.

    Raises :class:`InvalidURL` for a malformed or disallowed URL, and
    :class:`URLFetchError` for network failures or an oversized response.
    """
    url = (url or "").strip()
    if not url:
        raise InvalidURL("No URL provided")

    _validate_url(url)

    opener = build_opener(_SafeRedirectHandler())
    req = Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
    })

    try:
        with opener.open(req, timeout=FETCH_TIMEOUT_SECONDS) as res:
            raw = res.read(MAX_RESPONSE_BYTES + 1)
            encoding = res.headers.get("Content-Encoding", "")
    except HTTPError as exc:
        raise URLFetchError(f"URL returned HTTP {exc.code}", status_code=502) from exc
    except URLError as exc:
        raise URLFetchError(f"Could not fetch URL: {exc.reason}", status_code=502) from exc
    except socket.timeout as exc:
        raise URLFetchError("Fetching the URL timed out", status_code=504) from exc

    if len(raw) > MAX_RESPONSE_BYTES:
        raise URLFetchError("Response exceeded the maximum allowed size", status_code=502)

    if encoding == "gzip":
        raw = gzip.decompress(raw)
    elif encoding == "deflate":
        raw = zlib.decompress(raw)
    html = raw.decode("utf-8", errors="replace")

    parser = _FastText()
    parser.feed(html)
    return "\n".join(parser.parts)


__all__ = ["fetch_url_text"]
