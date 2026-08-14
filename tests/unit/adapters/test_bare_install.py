"""A bare install is a working install.

The dev environment has every extra, so an in-process test cannot prove that
clientwright works WITHOUT them: an accidental eager ``import httpx`` would pass
here and explode on a user's ``pip install clientwright``. These probes run in a
subprocess with the SDKs blocked at the import system level, which is the only
honest way to assert the promise.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

BLOCKED = (
    "httpx",
    "httpx2",
    "aiohttp",
    "requests",
    "urllib3",
    "prometheus_client",
    "opentelemetry",
    "dishka",
    "deadline_budget",
)

BLOCKER = """
import sys

BLOCKED = __BLOCKED__


class _NoExtras:
    \"\"\"Meta-path finder that makes every extra look uninstalled.\"\"\"

    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ModuleNotFoundError(f"no module named {name!r} (blocked by the bare-install probe)")
        return None


sys.meta_path.insert(0, _NoExtras())
"""


def run_probe(body: str) -> str:
    source = BLOCKER.replace("__BLOCKED__", repr(BLOCKED)) + textwrap.dedent(body)
    completed = subprocess.run(  # noqa: S603 - fixed argv, our own interpreter
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, f"probe failed:\n{completed.stdout}\n{completed.stderr}"
    return completed.stdout.strip()


def test__import_clientwright__pulls_in_no_sdk() -> None:
    output = run_probe(
        """
        import sys

        import clientwright

        leaked = sorted(m for m in sys.modules if m.split(".")[0] in BLOCKED)
        print(leaked or "clean")
        """
    )
    assert output == "clean"


def test__capabilities_matrix__builds_without_a_single_extra() -> None:
    output = run_probe(
        """
        import clientwright

        matrix = clientwright.capabilities_matrix()
        print(",".join(f"{name}:{caps.seam}" for name, caps in sorted(matrix.items())))
        """
    )
    assert output == "aiohttp:middleware,httpx:transport,httpx2:transport,requests:http_adapter,urllib3:urlopen"


def test__adapter_packages__import_without_their_sdk() -> None:
    output = run_probe(
        """
        import importlib

        names = ["httpx", "httpx2", "aiohttp", "requests", "urllib3", "observability"]
        for name in names:
            module = importlib.import_module(f"clientwright.adapters.{name}")
            assert module.__all__, name
        print("all packages importable")
        """
    )
    assert output == "all packages importable"


def test__touching_an_sdk_backed_name__raises_the_install_hint() -> None:
    output = run_probe(
        """
        import clientwright.adapters.aiohttp as adapter

        try:
            adapter.AiohttpAdapter
        except ImportError as error:
            print(error)
        else:
            print("NO ERROR")
        """
    )
    assert "clientwright[aiohttp]" in output


def test__building_without_the_extra__fails_with_the_install_hint() -> None:
    output = run_probe(
        """
        import clientwright

        config = clientwright.ClientConfig(service_name="probe")
        try:
            clientwright.build("httpx", config)
        except ImportError as error:
            print(error)
        else:
            print("NO ERROR")
        """
    )
    assert "clientwright[httpx]" in output


def test__zero_dep_surface__config_engine_and_testing_tools_work() -> None:
    output = run_probe(
        """
        import clientwright
        from clientwright.core.testing import ManualClock, OriginServer, RecordingMetrics

        config = clientwright.ClientConfig(service_name="probe", base_url="https://example.com")
        assert config.retry is not None and config.retry.max_attempts == 3
        with OriginServer() as origin:
            assert origin.url.startswith("http://127.0.0.1:")
        assert RecordingMetrics().inflight_balance == 0
        assert ManualClock(start=1.0)() == 1.0
        print("core usable")
        """
    )
    assert output == "core usable"
