"""Owned redirects: the engine follows hops, native following stays disabled.

One logical call therefore has ONE deadline, ONE retry budget and ONE circuit
signal regardless of hop count - on every adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin

from ..contracts.message import RequestView, ResponseView
from ..model import origin_of

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

# Stripped when a redirect crosses origins, mirroring urllib3's
# remove_headers_on_redirect and browser behavior.
CROSS_ORIGIN_STRIP = ("authorization", "proxy-authorization", "cookie")


@dataclass(frozen=True, slots=True)
class RedirectStep:
    url: str
    method: str | None
    drop_body: bool
    cross_origin: bool

    @property
    def needs_body_replay(self) -> bool:
        return not self.drop_body


def plan_redirect(response: ResponseView, request: RequestView) -> RedirectStep | None:
    """The next hop, or None when the response is not a followable redirect."""
    if response.status_code not in REDIRECT_STATUSES:
        return None
    location = response.location
    if not location:
        return None
    info = request.info
    url = urljoin(info.url, location)
    method: str | None = None
    drop_body = False
    if response.status_code == 303 or (response.status_code in (301, 302) and info.method == "POST"):
        if info.method != "HEAD":
            method = "GET"
        drop_body = True
    return RedirectStep(
        url=url,
        method=method,
        drop_body=drop_body,
        cross_origin=origin_of(url) != info.origin,
    )


def apply_redirect(request: RequestView, step: RedirectStep) -> None:
    if step.cross_origin:
        for name in CROSS_ORIGIN_STRIP:
            request.headers.pop(name, None)
    request.retarget(step.url, method=step.method, drop_body=step.drop_body)


__all__ = ["CROSS_ORIGIN_STRIP", "REDIRECT_STATUSES", "RedirectStep", "apply_redirect", "plan_redirect"]
