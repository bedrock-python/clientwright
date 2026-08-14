"""Owned-redirect planning: status handling, method demotion, origin changes."""

from __future__ import annotations

from clientwright.core.engine.redirects import apply_redirect, plan_redirect
from tests.helpers.views import FakeRequest, FakeResponse

# --- plan_redirect ---


def test__non_redirect_status__none() -> None:
    request = FakeRequest("GET", "https://a.example/x")
    assert plan_redirect(FakeResponse(200), request) is None


def test__redirect_without_location__none() -> None:
    request = FakeRequest("GET", "https://a.example/x")
    assert plan_redirect(FakeResponse(302), request) is None


def test__relative_location__resolved_against_request_url() -> None:
    request = FakeRequest("GET", "https://a.example/dir/x")
    step = plan_redirect(FakeResponse(302, {"Location": "/other"}), request)
    assert step is not None
    assert step.url == "https://a.example/other"
    assert step.method is None
    assert not step.cross_origin


def test__303_post__demoted_to_get_and_body_dropped() -> None:
    request = FakeRequest("POST", "https://a.example/x")
    step = plan_redirect(FakeResponse(303, {"Location": "/next"}), request)
    assert step is not None
    assert step.method == "GET"
    assert step.drop_body
    assert not step.needs_body_replay


def test__302_post__demoted_like_browsers_do() -> None:
    request = FakeRequest("POST", "https://a.example/x")
    step = plan_redirect(FakeResponse(302, {"Location": "/next"}), request)
    assert step is not None
    assert step.method == "GET"


def test__307_post__method_and_body_preserved() -> None:
    request = FakeRequest("POST", "https://a.example/x")
    step = plan_redirect(FakeResponse(307, {"Location": "/next"}), request)
    assert step is not None
    assert step.method is None
    assert not step.drop_body
    assert step.needs_body_replay


def test__cross_origin__detected() -> None:
    request = FakeRequest("GET", "https://a.example/x")
    step = plan_redirect(FakeResponse(302, {"Location": "https://b.example/y"}), request)
    assert step is not None
    assert step.cross_origin


# --- apply_redirect ---


def test__cross_origin_hop__strips_credentials_but_keeps_the_rest() -> None:
    request = FakeRequest("GET", "https://a.example/x")
    request.headers.update({"authorization": "Bearer x", "proxy-authorization": "y", "cookie": "c=1", "accept": "json"})
    step = plan_redirect(FakeResponse(302, {"Location": "https://b.example/y"}), request)
    assert step is not None
    apply_redirect(request, step)
    assert set(request.headers) == {"accept"}


def test__same_origin_hop__keeps_credentials() -> None:
    request = FakeRequest("GET", "https://a.example/x")
    request.headers["authorization"] = "Bearer x"
    step = plan_redirect(FakeResponse(302, {"Location": "/y"}), request)
    assert step is not None
    apply_redirect(request, step)
    assert request.headers["authorization"] == "Bearer x"
