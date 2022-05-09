import socket
import sys
from typing import List
from unittest.mock import patch

import pytest
from asgiref.typing import ASGIReceiveCallable, ASGISendCallable, Scope

from uvicorn._subprocess import SpawnProcess, get_subprocess, subprocess_started
from uvicorn.config import Config


def server_run(sockets: List[socket.socket]):  # pragma: no cover
    ...


async def app(
    scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable
) -> None:  # pragma: no cover
    ...


@pytest.mark.skipif(sys.platform == "win32", reason="require unix-like system")
def test_get_subprocess() -> None:  # pragma: py-win32
    fdsock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    fd = fdsock.fileno()
    config = Config(app=app, fd=fd)
    config.load()

    process = get_subprocess(config, server_run, [fdsock])
    assert isinstance(process, SpawnProcess)

    fdsock.close()


@pytest.mark.skipif(sys.platform == "win32", reason="require unix-like system")
def test_subprocess_started() -> None:  # pragma: py-win32
    fdsock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    fd = fdsock.fileno()
    config = Config(app=app, fd=fd)
    config.load()

    with patch("tests.test_subprocess.server_run") as mock_run:
        with patch.object(config, "configure_logging") as mock_config_logging:
            subprocess_started(config, server_run, [fdsock], None)
            mock_run.assert_called_once()
            mock_config_logging.assert_called_once()

    fdsock.close()
