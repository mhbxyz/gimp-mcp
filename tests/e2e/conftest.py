"""End-to-end fixtures: a real headless GIMP 3 + the MCP server over stdio.

GIMP runs with an isolated configuration directory (``GIMP3_DIRECTORY``) in a
temporary directory, so personal settings, plug-ins and files are never used.
When GIMP is missing the tests are skipped with an explicit reason, unless
``GIMP_MCP_REQUIRE_GIMP=1`` (set in CI) which turns that into a failure.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from gimp_mcp.headless import HeadlessGimp, find_gimp_console

REQUIRE_GIMP = os.environ.get("GIMP_MCP_REQUIRE_GIMP") == "1"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/e2e/" in str(item.fspath).replace(os.sep, "/"):
            item.add_marker(pytest.mark.gimp)


def _gimp_or_skip() -> str:
    console = find_gimp_console()
    if console is None:
        message = "GIMP 3 (gimp-console) not found on PATH"
        if REQUIRE_GIMP:
            pytest.fail(message + " and GIMP_MCP_REQUIRE_GIMP=1", pytrace=False)
        pytest.skip(message)
    return console


@pytest.fixture(scope="session")
def gimp() -> Iterator[HeadlessGimp]:
    """One headless GIMP for the whole test session (fast); tests clean their images."""
    console = _gimp_or_skip()
    instance = HeadlessGimp(console=console)
    instance.start()
    try:
        yield instance
    finally:
        instance.stop()


@pytest.fixture
def gimp_factory() -> Iterator[Callable[..., HeadlessGimp]]:
    """Start dedicated GIMP instances (e.g. with files opened at launch, or to kill them)."""
    console = _gimp_or_skip()
    started: list[HeadlessGimp] = []

    def start(open_files: list[Path] | None = None) -> HeadlessGimp:
        instance = HeadlessGimp(console=console, open_files=open_files or [])
        started.append(instance)
        instance.start()
        return instance

    try:
        yield start
    finally:
        for instance in started:
            instance.stop()


def server_params(gimp: HeadlessGimp, extra_env: dict[str, str] | None = None) -> StdioServerParameters:
    env = {
        "GIMP_MCP_SOCKET": str(gimp.socket_path),
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
    }
    env.update(extra_env or {})
    return StdioServerParameters(command=sys.executable, args=["-m", "gimp_mcp", "serve"], env=env)


@asynccontextmanager
async def mcp_client(gimp: HeadlessGimp, extra_env: dict[str, str] | None = None) -> AsyncIterator[Client]:
    async with Client(server_params(gimp, extra_env), read_timeout_seconds=120) as client:
        yield client


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    return tmp_path


def assets_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "assets"


def have(executable: str) -> bool:
    return shutil.which(executable) is not None
