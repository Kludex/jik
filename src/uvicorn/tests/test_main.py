import asyncio
import platform
import socket
import sys
import threading
import time

import pytest
import requests

from uvicorn.config import Config
from uvicorn.main import Server


def test_run():
    class App:
        def __init__(self, scope):
            if scope["type"] != "http":
                raise Exception()

        async def __call__(self, receive, send):
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b"", "more_body": False})

    class CustomServer(Server):
        def install_signal_handlers(self):
            pass

    config = Config(app=App, loop="asyncio", limit_max_requests=1)
    server = CustomServer(config=config)
    thread = threading.Thread(target=server.run)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    response = requests.get("http://127.0.0.1:8000")
    assert response.status_code == 204
    thread.join()


def test_run_multiprocess():
    class App:
        def __init__(self, scope):
            if scope["type"] != "http":
                raise Exception()

        async def __call__(self, receive, send):
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b"", "more_body": False})

    class CustomServer(Server):
        def install_signal_handlers(self):
            pass

    config = Config(app=App, loop="asyncio", workers=2, limit_max_requests=1)
    server = CustomServer(config=config)
    thread = threading.Thread(target=server.run)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    response = requests.get("http://127.0.0.1:8000")
    assert response.status_code == 204
    thread.join()


def test_run_reload():
    class App:
        def __init__(self, scope):
            if scope["type"] != "http":
                raise Exception()

        async def __call__(self, receive, send):
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b"", "more_body": False})

    class CustomServer(Server):
        def install_signal_handlers(self):
            pass

    config = Config(app=App, loop="asyncio", reload=True, limit_max_requests=1)
    server = CustomServer(config=config)
    thread = threading.Thread(target=server.run)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    response = requests.get("http://127.0.0.1:8000")
    assert response.status_code == 204
    thread.join()


def test_run_with_shutdown():
    class App:
        def __init__(self, scope):
            if scope["type"] != "http":
                raise Exception()

        async def __call__(self, receive, send):
            while True:
                time.sleep(1)

    class CustomServer(Server):
        def install_signal_handlers(self):
            pass

    config = Config(app=App, loop="asyncio", workers=2, limit_max_requests=1)
    server = CustomServer(config=config)
    sock = config.bind_socket()
    exc = True

    def safe_run():
        nonlocal exc, server
        try:
            exc = None
            config.setup_event_loop()
            loop = asyncio.get_event_loop()
            loop.run_until_complete(server.serve(sockets=[sock]))
        except Exception as e:
            exc = e

    thread = threading.Thread(target=safe_run)
    thread.start()

    while not server.started:
        time.sleep(0.01)

    server.should_exit = True
    thread.join()
    assert exc is None


@pytest.mark.skipif(
    sys.platform.startswith("win") or platform.python_implementation() == "PyPy",
    reason="Skipping uds test on Windows and pypy",
)
def test_run_uds(tmp_path):
    class App:
        def __init__(self, scope):
            if scope["type"] != "http":
                raise Exception()

        async def __call__(self, receive, send):
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b"", "more_body": False})

    class CustomServer(Server):
        def install_signal_handlers(self):
            pass

    uds = str(tmp_path / "socket")
    config = Config(app=App, loop="asyncio", limit_max_requests=1, uds=uds)
    server = CustomServer(config=config)
    thread = threading.Thread(target=server.run)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    data = b"GET / HTTP/1.1\r\n\r\n"
    sock_client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock_client.connect(uds)
        r = sock_client.sendall(data)
        assert r is None
    except Exception as e:
        print(e)
    finally:
        sock_client.close()
    thread.join()


@pytest.mark.skipif(
    sys.platform.startswith("win") or platform.python_implementation() == "PyPy",
    reason="Skipping fd test on Windows and pypy",
)
def test_run_fd(tmp_path):
    class App:
        def __init__(self, scope):
            if scope["type"] != "http":
                raise Exception()

        async def __call__(self, receive, send):
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b"", "more_body": False})

    class CustomServer(Server):
        def install_signal_handlers(self):
            pass

    uds = str(tmp_path / "socket")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    fd = sock.fileno()
    sock.bind(uds)
    config = Config(app=App, loop="asyncio", limit_max_requests=1, fd=fd)
    server = CustomServer(config=config)
    thread = threading.Thread(target=server.run)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    data = b"GET / HTTP/1.1\r\n\r\n"
    sock_client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock_client.connect(uds)
        r = sock_client.sendall(data)
        assert r is None
    except Exception as e:
        print(e)
    finally:
        sock_client.close()
        sock.close()
    thread.join()
