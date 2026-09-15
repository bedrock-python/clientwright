"""servicewright integration (``[servicewright]`` extra).

servicewright binds the ids of the unit of work being served (``request_id``,
``user_id``, ``tenant_id``, ``trace_id``) into its request context, and
``servicewright.propagation_metadata`` reads them back as outbound headers.
That function already satisfies clientwright's ``HeaderProvider`` protocol
bare; this module names the join so no service writes it by hand::

    from clientwright.contrib.servicewright import servicewright_headers

    deps = AdapterDeps(header_providers=servicewright_headers())
    client = build("httpx", config, deps)

    await client.get("/users")  # carries x-request-id and friends, when bound

Outside a bound context the provider returns nothing and the request goes out
as before. The helper returns the providers tuple rather than a whole
``AdapterDeps`` so it composes with everything else injected there -
``contrib.deadline`` included - instead of competing with it.

Unlike ``contrib.deadline`` there is nothing structural to type here; the real
function is the point, so servicewright is imported at module import time and
a missing extra fails right here with an install hint.
"""

from __future__ import annotations

try:
    from servicewright import propagation_metadata
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError("servicewright integration requires clientwright[servicewright]; install it.") from exc

from ..core.contracts.context import HeaderProvider


def servicewright_headers() -> tuple[HeaderProvider, ...]:
    """The header providers carrying servicewright's request context upstream.

    ``(propagation_metadata,)`` under servicewright's standard mapping - the
    request, user, tenant and trace ids as ``x-request-id``, ``x-user-id``,
    ``x-tenant-id`` and ``x-trace-id``. For a different mapping build the tuple
    yourself: ``(partial(propagation_metadata, keys),)``.
    """
    return (propagation_metadata,)


__all__ = ["servicewright_headers"]
