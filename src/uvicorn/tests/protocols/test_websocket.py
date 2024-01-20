from __future__ import annotations

import asyncio
import typing
from copy import deepcopy

import httpx
import pytest
import websockets
import websockets.client
import websockets.exceptions
from websockets.extensions.permessage_deflate import ClientPerMessageDeflateFactory
from websockets.typing import Subprotocol

from tests.response import Response
from tests.utils import run_server
from uvicorn._types import (
    ASGIReceiveCallable,
    ASGIReceiveEvent,
    ASGISendCallable,
    Scope,
    WebSocketCloseEvent,
    WebSocketDisconnectEvent,
    WebSocketResponseStartEvent,
)
from uvicorn.config import Config
from uvicorn.protocols.websockets.websockets_impl import WebSocketProtocol

try:
    from uvicorn.protocols.websockets.wsproto_impl import WSProtocol as _WSProtocol

    skip_if_no_wsproto = pytest.mark.skipif(False, reason="wsproto is installed.")
except ModuleNotFoundError:
    skip_if_no_wsproto = pytest.mark.skipif(True, reason="wsproto is not installed.")

if typing.TYPE_CHECKING:
    import sys

    from uvicorn.protocols.http.h11_impl import H11Protocol
    from uvicorn.protocols.http.httptools_impl import HttpToolsProtocol
    from uvicorn.protocols.websockets.wsproto_impl import WSProtocol as _WSProtocol

    if sys.version_info >= (3, 10):  # pragma: no cover
        from typing import TypeAlias
    else:  # pragma: no cover
        from typing_extensions import TypeAlias

    HTTPProtocol: TypeAlias = "type[H11Protocol | HttpToolsProtocol]"
    WSProtocol: TypeAlias = "type[_WSProtocol | WebSocketProtocol]"


class WebSocketResponse:
    def __init__(
        self, scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ):
        self.scope = scope
        self.receive = receive
        self.send = send

    def __await__(self):
        return self.asgi().__await__()

    async def asgi(self):
        while True:
            message = await self.receive()
            message_type = message["type"].replace(".", "_")
            handler = getattr(self, message_type, None)
            if handler is not None:
                await handler(message)
            if message_type == "websocket_disconnect":
                break


async def wsresponse(url):
    """
    A simple websocket connection request and response helper
    """
    url = url.replace("ws:", "http:")
    headers = {
        "connection": "upgrade",
        "upgrade": "websocket",
        "Sec-WebSocket-Key": "x3JJHMbDL1EzLkh9GBhXDw==",
        "Sec-WebSocket-Version": "13",
    }
    async with httpx.AsyncClient() as client:
        return await client.get(url, headers=headers)


@pytest.mark.anyio
async def test_invalid_upgrade(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    def app(scope: Scope):
        return None

    config = Config(
        app=app, ws=ws_protocol_cls, http=http_protocol_cls, port=unused_tcp_port
    )
    async with run_server(config):
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"http://127.0.0.1:{unused_tcp_port}",
                headers={
                    "upgrade": "websocket",
                    "connection": "upgrade",
                    "sec-webSocket-version": "11",
                },
            )
        if response.status_code == 426:
            # response.text == ""
            pass  # ok, wsproto 0.13
        else:
            assert response.status_code == 400
            assert (
                response.text.lower().strip().rstrip(".")
                in [
                    "missing sec-websocket-key header",
                    "missing sec-websocket-version header",  # websockets
                    "missing or empty sec-websocket-key header",  # wsproto
                    "failed to open a websocket connection: missing "
                    "sec-websocket-key header",
                    "failed to open a websocket connection: missing or empty "
                    "sec-websocket-key header",
                ]
            )


@pytest.mark.anyio
async def test_accept_connection(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send({"type": "websocket.accept"})

    async def open_connection(url):
        async with websockets.client.connect(url) as websocket:
            return websocket.open

    config = Config(
        app=App,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        is_open = await open_connection(f"ws://127.0.0.1:{unused_tcp_port}")
        assert is_open


@pytest.mark.anyio
async def test_shutdown(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send({"type": "websocket.accept"})

    config = Config(
        app=App,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config) as server:
        async with websockets.client.connect(f"ws://127.0.0.1:{unused_tcp_port}"):
            # Attempt shutdown while connection is still open
            await server.shutdown()


@pytest.mark.anyio
async def test_supports_permessage_deflate_extension(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send({"type": "websocket.accept"})

    async def open_connection(url):
        extension_factories = [ClientPerMessageDeflateFactory()]
        async with websockets.client.connect(
            url, extensions=extension_factories
        ) as websocket:
            return [extension.name for extension in websocket.extensions]

    config = Config(
        app=App,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        extension_names = await open_connection(f"ws://127.0.0.1:{unused_tcp_port}")
        assert "permessage-deflate" in extension_names


@pytest.mark.anyio
async def test_can_disable_permessage_deflate_extension(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send({"type": "websocket.accept"})

    async def open_connection(url: str):
        # enable per-message deflate on the client, so that we can check the server
        # won't support it when it's disabled.
        extension_factories = [ClientPerMessageDeflateFactory()]
        async with websockets.client.connect(
            url, extensions=extension_factories
        ) as websocket:
            return [extension.name for extension in websocket.extensions]

    config = Config(
        app=App,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        ws_per_message_deflate=False,
        port=unused_tcp_port,
    )
    async with run_server(config):
        extension_names = await open_connection(f"ws://127.0.0.1:{unused_tcp_port}")
        assert "permessage-deflate" not in extension_names


@pytest.mark.anyio
async def test_close_connection(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send({"type": "websocket.close"})

    async def open_connection(url: str):
        try:
            await websockets.client.connect(url)
        except websockets.exceptions.InvalidHandshake:
            return False
        return True  # pragma: no cover

    config = Config(
        app=App,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        is_open = await open_connection(f"ws://127.0.0.1:{unused_tcp_port}")
        assert not is_open


@pytest.mark.anyio
async def test_headers(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            headers = self.scope.get("headers")
            headers = dict(headers)  # type: ignore
            assert headers[b"host"].startswith(b"127.0.0.1")  # type: ignore
            assert headers[b"username"] == bytes("abraão", "utf-8")  # type: ignore
            await self.send({"type": "websocket.accept"})

    async def open_connection(url: str):
        async with websockets.client.connect(
            url, extra_headers=[("username", "abraão")]
        ) as websocket:
            return websocket.open

    config = Config(
        app=App,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        is_open = await open_connection(f"ws://127.0.0.1:{unused_tcp_port}")
        assert is_open


@pytest.mark.anyio
async def test_extra_headers(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send(
                {"type": "websocket.accept", "headers": [(b"extra", b"header")]}
            )

    async def open_connection(url: str):
        async with websockets.client.connect(url) as websocket:
            return websocket.response_headers

    config = Config(
        app=App,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        extra_headers = await open_connection(f"ws://127.0.0.1:{unused_tcp_port}")
        assert extra_headers.get("extra") == "header"


@pytest.mark.anyio
async def test_path_and_raw_path(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            path = self.scope.get("path")
            raw_path = self.scope.get("raw_path")
            assert path == "/one/two"
            assert raw_path == b"/one%2Ftwo"
            await self.send({"type": "websocket.accept"})

    async def open_connection(url: str):
        async with websockets.client.connect(url) as websocket:
            return websocket.open

    config = Config(
        app=App,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        is_open = await open_connection(f"ws://127.0.0.1:{unused_tcp_port}/one%2Ftwo")
        assert is_open


@pytest.mark.anyio
async def test_send_text_data_to_client(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send({"type": "websocket.accept"})
            await self.send({"type": "websocket.send", "text": "123"})

    async def get_data(url: str):
        async with websockets.client.connect(url) as websocket:
            return await websocket.recv()

    config = Config(
        app=App,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        data = await get_data(f"ws://127.0.0.1:{unused_tcp_port}")
        assert data == "123"


@pytest.mark.anyio
async def test_send_binary_data_to_client(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send({"type": "websocket.accept"})
            await self.send({"type": "websocket.send", "bytes": b"123"})

    async def get_data(url: str):
        async with websockets.client.connect(url) as websocket:
            return await websocket.recv()

    config = Config(
        app=App,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        data = await get_data(f"ws://127.0.0.1:{unused_tcp_port}")
        assert data == b"123"


@pytest.mark.anyio
async def test_send_and_close_connection(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send({"type": "websocket.accept"})
            await self.send({"type": "websocket.send", "text": "123"})
            await self.send({"type": "websocket.close"})

    async def get_data(url: str):
        async with websockets.client.connect(url) as websocket:
            data = await websocket.recv()
            is_open = True
            try:
                await websocket.recv()
            except Exception:
                is_open = False
            return (data, is_open)

    config = Config(
        app=App,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        (data, is_open) = await get_data(f"ws://127.0.0.1:{unused_tcp_port}")
        assert data == "123"
        assert not is_open


@pytest.mark.anyio
async def test_send_text_data_to_server(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send({"type": "websocket.accept"})

        async def websocket_receive(self, message):
            _text = message.get("text")
            await self.send({"type": "websocket.send", "text": _text})

    async def send_text(url: str):
        async with websockets.client.connect(url) as websocket:
            await websocket.send("abc")
            return await websocket.recv()

    config = Config(
        app=App,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        data = await send_text(f"ws://127.0.0.1:{unused_tcp_port}")
        assert data == "abc"


@pytest.mark.anyio
async def test_send_binary_data_to_server(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send({"type": "websocket.accept"})

        async def websocket_receive(self, message):
            _bytes = message.get("bytes")
            await self.send({"type": "websocket.send", "bytes": _bytes})

    async def send_text(url: str):
        async with websockets.client.connect(url) as websocket:
            await websocket.send(b"abc")
            return await websocket.recv()

    config = Config(
        app=App,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        data = await send_text(f"ws://127.0.0.1:{unused_tcp_port}")
        assert data == b"abc"


@pytest.mark.anyio
async def test_send_after_protocol_close(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send({"type": "websocket.accept"})
            await self.send({"type": "websocket.send", "text": "123"})
            await self.send({"type": "websocket.close"})
            with pytest.raises(Exception):
                await self.send({"type": "websocket.send", "text": "123"})

    async def get_data(url: str):
        async with websockets.client.connect(url) as websocket:
            data = await websocket.recv()
            is_open = True
            try:
                await websocket.recv()
            except Exception:
                is_open = False
            return (data, is_open)

    config = Config(
        app=App,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        (data, is_open) = await get_data(f"ws://127.0.0.1:{unused_tcp_port}")
        assert data == "123"
        assert not is_open


@pytest.mark.anyio
async def test_missing_handshake(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    async def app(scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable):
        pass

    async def connect(url: str):
        await websockets.client.connect(url)

    config = Config(
        app=app,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        with pytest.raises(websockets.exceptions.InvalidStatusCode) as exc_info:
            await connect(f"ws://127.0.0.1:{unused_tcp_port}")
        assert exc_info.value.status_code == 500


@pytest.mark.anyio
async def test_send_before_handshake(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    async def app(scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable):
        await send({"type": "websocket.send", "text": "123"})

    async def connect(url: str):
        await websockets.client.connect(url)

    config = Config(
        app=app,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        with pytest.raises(websockets.exceptions.InvalidStatusCode) as exc_info:
            await connect(f"ws://127.0.0.1:{unused_tcp_port}")
        assert exc_info.value.status_code == 500


@pytest.mark.anyio
async def test_duplicate_handshake(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    async def app(scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable):
        await send({"type": "websocket.accept"})
        await send({"type": "websocket.accept"})

    async def connect(url: str):
        async with websockets.client.connect(url) as websocket:
            _ = await websocket.recv()

    config = Config(
        app=app,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        with pytest.raises(websockets.exceptions.ConnectionClosed) as exc_info:
            await connect(f"ws://127.0.0.1:{unused_tcp_port}")
        assert exc_info.value.code == 1006


@pytest.mark.anyio
async def test_asgi_return_value(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    """
    The ASGI callable should return 'None'. If it doesn't, make sure that
    the connection is closed with an error condition.
    """

    async def app(scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable):
        await send({"type": "websocket.accept"})
        return 123

    async def connect(url: str):
        async with websockets.client.connect(url) as websocket:
            _ = await websocket.recv()

    config = Config(
        app=app,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        with pytest.raises(websockets.exceptions.ConnectionClosed) as exc_info:
            await connect(f"ws://127.0.0.1:{unused_tcp_port}")
        assert exc_info.value.code == 1006


@pytest.mark.anyio
@pytest.mark.parametrize("code", [None, 1000, 1001])
@pytest.mark.parametrize(
    "reason",
    [None, "test", False],
    ids=["none_as_reason", "normal_reason", "without_reason"],
)
async def test_app_close(
    ws_protocol_cls: WSProtocol,
    http_protocol_cls: HTTPProtocol,
    unused_tcp_port: int,
    code: int | None,
    reason: str | None,
):
    async def app(scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable):
        while True:
            message = await receive()
            if message["type"] == "websocket.connect":
                await send({"type": "websocket.accept"})
            elif message["type"] == "websocket.receive":
                reply: WebSocketCloseEvent = {"type": "websocket.close"}

                if code is not None:
                    reply["code"] = code

                if reason is not False:
                    reply["reason"] = reason

                await send(reply)
            elif message["type"] == "websocket.disconnect":
                break

    async def websocket_session(url: str):
        async with websockets.client.connect(url) as websocket:
            await websocket.ping()
            await websocket.send("abc")
            await websocket.recv()

    config = Config(
        app=app,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        with pytest.raises(websockets.exceptions.ConnectionClosed) as exc_info:
            await websocket_session(f"ws://127.0.0.1:{unused_tcp_port}")
        assert exc_info.value.code == (code or 1000)
        assert exc_info.value.reason == (reason or "")


@pytest.mark.anyio
async def test_client_close(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    async def app(scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable):
        while True:
            message = await receive()
            if message["type"] == "websocket.connect":
                await send({"type": "websocket.accept"})
            elif message["type"] == "websocket.receive":
                pass
            elif message["type"] == "websocket.disconnect":
                break

    async def websocket_session(url: str):
        async with websockets.client.connect(url) as websocket:
            await websocket.ping()
            await websocket.send("abc")

    config = Config(
        app=app,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        await websocket_session(f"ws://127.0.0.1:{unused_tcp_port}")


@pytest.mark.anyio
async def test_client_connection_lost(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    got_disconnect_event = False

    async def app(scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable):
        nonlocal got_disconnect_event
        while True:
            message = await receive()
            if message["type"] == "websocket.connect":
                await send({"type": "websocket.accept"})
            elif message["type"] == "websocket.disconnect":
                break

        got_disconnect_event = True

    config = Config(
        app=app,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        ws_ping_interval=0.0,
        port=unused_tcp_port,
    )
    async with run_server(config):
        async with websockets.client.connect(
            f"ws://127.0.0.1:{unused_tcp_port}"
        ) as websocket:
            websocket.transport.close()
            await asyncio.sleep(0.1)
            got_disconnect_event_before_shutdown = got_disconnect_event

    assert got_disconnect_event_before_shutdown is True


@pytest.mark.anyio
async def test_client_connection_lost_on_send(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    disconnect = asyncio.Event()
    got_disconnect_event = False

    async def app(scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable):
        nonlocal got_disconnect_event
        message = await receive()
        if message["type"] == "websocket.connect":
            await send({"type": "websocket.accept"})
        try:
            await disconnect.wait()
            await send({"type": "websocket.send", "text": "123"})
        except IOError:
            got_disconnect_event = True

    config = Config(
        app=app,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        url = f"ws://127.0.0.1:{unused_tcp_port}"
        async with websockets.client.connect(url):
            await asyncio.sleep(0.1)
        disconnect.set()

    assert got_disconnect_event is True


@pytest.mark.anyio
async def test_connection_lost_before_handshake_complete(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    send_accept_task = asyncio.Event()
    disconnect_message: WebSocketDisconnectEvent = {}  # type: ignore

    async def app(scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable):
        nonlocal disconnect_message
        message = await receive()
        if message["type"] == "websocket.connect":
            await send_accept_task.wait()
        disconnect_message = await receive()  # type: ignore

    response: typing.Optional[httpx.Response] = None

    async def websocket_session(uri: str):
        nonlocal response
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"http://127.0.0.1:{unused_tcp_port}",
                headers={
                    "upgrade": "websocket",
                    "connection": "upgrade",
                    "sec-websocket-version": "13",
                    "sec-websocket-key": "dGhlIHNhbXBsZSBub25jZQ==",
                },
            )

    config = Config(
        app=app,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        task = asyncio.create_task(
            websocket_session(f"ws://127.0.0.1:{unused_tcp_port}")
        )
        await asyncio.sleep(0.1)
        send_accept_task.set()
        await asyncio.sleep(0.1)

    assert response is not None
    assert response.status_code == 500, response.text
    assert response.text == "Internal Server Error"
    assert disconnect_message == {"type": "websocket.disconnect", "code": 1006}
    await task


@pytest.mark.anyio
async def test_send_close_on_server_shutdown(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    disconnect_message: WebSocketDisconnectEvent = {}  # type: ignore
    server_shutdown_event = asyncio.Event()

    async def app(scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable):
        nonlocal disconnect_message
        while True:
            message = await receive()
            if message["type"] == "websocket.connect":
                await send({"type": "websocket.accept"})
            elif message["type"] == "websocket.disconnect":
                disconnect_message = message
                break

    websocket: typing.Optional[websockets.client.WebSocketClientProtocol] = None

    async def websocket_session(uri: str):
        nonlocal websocket
        async with websockets.client.connect(uri) as ws_connection:
            websocket = ws_connection
            await server_shutdown_event.wait()

    config = Config(
        app=app,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        task = asyncio.create_task(
            websocket_session(f"ws://127.0.0.1:{unused_tcp_port}")
        )
        await asyncio.sleep(0.1)
        disconnect_message_before_shutdown = disconnect_message
    server_shutdown_event.set()

    assert websocket is not None
    assert websocket.close_code == 1012
    assert disconnect_message_before_shutdown == {}
    assert disconnect_message == {"type": "websocket.disconnect", "code": 1012}
    task.cancel()


@pytest.mark.anyio
@pytest.mark.parametrize("subprotocol", ["proto1", "proto2"])
async def test_subprotocols(
    ws_protocol_cls: WSProtocol,
    http_protocol_cls: HTTPProtocol,
    subprotocol: str,
    unused_tcp_port: int,
):
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send({"type": "websocket.accept", "subprotocol": subprotocol})

    async def get_subprotocol(url: str):
        async with websockets.client.connect(
            url, subprotocols=[Subprotocol("proto1"), Subprotocol("proto2")]
        ) as websocket:
            return websocket.subprotocol

    config = Config(
        app=App,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        accepted_subprotocol = await get_subprotocol(
            f"ws://127.0.0.1:{unused_tcp_port}"
        )
        assert accepted_subprotocol == subprotocol


MAX_WS_BYTES = 1024 * 1024 * 16
MAX_WS_BYTES_PLUS1 = MAX_WS_BYTES + 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    "client_size_sent, server_size_max, expected_result",
    [
        (MAX_WS_BYTES, MAX_WS_BYTES, 0),
        (MAX_WS_BYTES_PLUS1, MAX_WS_BYTES, 1009),
        (10, 10, 0),
        (11, 10, 1009),
    ],
    ids=[
        "max=defaults sent=defaults",
        "max=defaults sent=defaults+1",
        "max=10 sent=10",
        "max=10 sent=11",
    ],
)
async def test_send_binary_data_to_server_bigger_than_default_on_websockets(
    http_protocol_cls: HTTPProtocol,
    client_size_sent: int,
    server_size_max: int,
    expected_result: int,
    unused_tcp_port: int,
):
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send({"type": "websocket.accept"})

        async def websocket_receive(self, message):
            _bytes = message.get("bytes")
            await self.send({"type": "websocket.send", "bytes": _bytes})

    async def send_text(url: str):
        async with websockets.client.connect(url, max_size=client_size_sent) as ws:
            await ws.send(b"\x01" * client_size_sent)
            return await ws.recv()

    config = Config(
        app=App,
        ws=WebSocketProtocol,
        http=http_protocol_cls,
        lifespan="off",
        ws_max_size=server_size_max,
        port=unused_tcp_port,
    )
    async with run_server(config):
        if expected_result == 0:
            data = await send_text(f"ws://127.0.0.1:{unused_tcp_port}")
            assert data == b"\x01" * client_size_sent
        else:
            with pytest.raises(websockets.exceptions.ConnectionClosedError) as e:
                data = await send_text(f"ws://127.0.0.1:{unused_tcp_port}")
            assert e.value.code == expected_result


@pytest.mark.anyio
async def test_server_reject_connection(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    disconnected_message: ASGIReceiveEvent = {}  # type: ignore

    async def app(scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable):
        nonlocal disconnected_message
        assert scope["type"] == "websocket"

        # Pull up first recv message.
        message = await receive()
        assert message["type"] == "websocket.connect"

        # Reject the connection.
        await send({"type": "websocket.close"})
        # -- At this point websockets' recv() is unusable. --

        # This doesn't raise `TypeError`:
        # See https://github.com/encode/uvicorn/issues/244
        disconnected_message = await receive()

    async def websocket_session(url):
        with pytest.raises(websockets.exceptions.InvalidStatusCode) as exc_info:
            async with websockets.client.connect(url):
                pass  # pragma: no cover
        assert exc_info.value.status_code == 403

    config = Config(
        app=app,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        await websocket_session(f"ws://127.0.0.1:{unused_tcp_port}")

    assert disconnected_message == {"type": "websocket.disconnect", "code": 1006}


@pytest.mark.anyio
async def test_server_reject_connection_with_response(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    disconnected_message = {}

    async def app(scope, receive, send):
        nonlocal disconnected_message
        assert scope["type"] == "websocket"
        assert "websocket.http.response" in scope["extensions"]

        # Pull up first recv message.
        message = await receive()
        assert message["type"] == "websocket.connect"

        # Reject the connection with a response
        response = Response(b"goodbye", status_code=400)
        await response(scope, receive, send)
        disconnected_message = await receive()

    async def websocket_session(url):
        response = await wsresponse(url)
        assert response.status_code == 400
        assert response.content == b"goodbye"

    config = Config(
        app=app,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        await websocket_session(f"ws://127.0.0.1:{unused_tcp_port}")

    assert disconnected_message == {"type": "websocket.disconnect", "code": 1006}


@pytest.mark.anyio
async def test_server_reject_connection_with_multibody_response(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    disconnected_message: ASGIReceiveEvent = {}  # type: ignore

    async def app(scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable):
        nonlocal disconnected_message
        assert scope["type"] == "websocket"
        assert "extensions" in scope
        assert "websocket.http.response" in scope["extensions"]

        # Pull up first recv message.
        message = await receive()
        assert message["type"] == "websocket.connect"
        await send(
            {
                "type": "websocket.http.response.start",
                "status": 400,
                "headers": [
                    (b"Content-Length", b"20"),
                    (b"Content-Type", b"text/plain"),
                ],
            }
        )
        await send(
            {
                "type": "websocket.http.response.body",
                "body": b"x" * 10,
                "more_body": True,
            }
        )
        await send({"type": "websocket.http.response.body", "body": b"y" * 10})
        disconnected_message = await receive()

    async def websocket_session(url: str):
        response = await wsresponse(url)
        assert response.status_code == 400
        assert response.content == (b"x" * 10) + (b"y" * 10)

    config = Config(
        app=app,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        await websocket_session(f"ws://127.0.0.1:{unused_tcp_port}")

    assert disconnected_message == {"type": "websocket.disconnect", "code": 1006}


@pytest.mark.anyio
async def test_server_reject_connection_with_invalid_status(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    # this test checks that even if there is an error in the response, the server
    # can successfully send a 500 error back to the client
    async def app(scope, receive, send):
        assert scope["type"] == "websocket"
        assert "websocket.http.response" in scope["extensions"]

        # Pull up first recv message.
        message = await receive()
        assert message["type"] == "websocket.connect"

        message = {
            "type": "websocket.http.response.start",
            "status": 700,  # invalid status code
            "headers": [(b"Content-Length", b"0"), (b"Content-Type", b"text/plain")],
        }
        await send(message)
        message = {
            "type": "websocket.http.response.body",
            "body": b"",
        }
        await send(message)

    async def websocket_session(url):
        response = await wsresponse(url)
        assert response.status_code == 500
        assert response.content == b"Internal Server Error"

    config = Config(
        app=app,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        await websocket_session(f"ws://127.0.0.1:{unused_tcp_port}")


@pytest.mark.anyio
async def test_server_reject_connection_with_body_nolength(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    # test that the server can send a response with a body but no content-length
    async def app(scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable):
        assert scope["type"] == "websocket"
        assert "extensions" in scope
        assert "websocket.http.response" in scope["extensions"]

        # Pull up first recv message.
        message = await receive()
        assert message["type"] == "websocket.connect"

        await send(
            {
                "type": "websocket.http.response.start",
                "status": 403,
                "headers": [],
            }
        )
        await send({"type": "websocket.http.response.body", "body": b"hardbody"})

    async def websocket_session(url):
        response = await wsresponse(url)
        assert response.status_code == 403
        assert response.content == b"hardbody"
        if ws_protocol_cls == _WSProtocol:
            # wsproto automatically makes the message chunked
            assert response.headers["transfer-encoding"] == "chunked"
        else:
            # websockets automatically adds a content-length
            assert response.headers["content-length"] == "8"

    config = Config(
        app=app,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        await websocket_session(f"ws://127.0.0.1:{unused_tcp_port}")


@pytest.mark.anyio
async def test_server_reject_connection_with_invalid_msg(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    async def app(scope, receive, send):
        assert scope["type"] == "websocket"
        assert "websocket.http.response" in scope["extensions"]

        # Pull up first recv message.
        message = await receive()
        assert message["type"] == "websocket.connect"

        message = {
            "type": "websocket.http.response.start",
            "status": 404,
            "headers": [(b"Content-Length", b"0"), (b"Content-Type", b"text/plain")],
        }
        await send(message)
        # send invalid message.  This will raise an exception here
        await send(message)

    async def websocket_session(url):
        with pytest.raises(websockets.exceptions.InvalidStatusCode) as exc_info:
            async with websockets.client.connect(url):
                pass  # pragma: no cover
        assert exc_info.value.status_code == 404

    config = Config(
        app=app,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        await websocket_session(f"ws://127.0.0.1:{unused_tcp_port}")


@pytest.mark.anyio
async def test_server_reject_connection_with_missing_body(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    async def app(scope, receive, send):
        assert scope["type"] == "websocket"
        assert "websocket.http.response" in scope["extensions"]

        # Pull up first recv message.
        message = await receive()
        assert message["type"] == "websocket.connect"

        message = {
            "type": "websocket.http.response.start",
            "status": 404,
            "headers": [(b"Content-Length", b"0"), (b"Content-Type", b"text/plain")],
        }
        await send(message)
        # no further message

    async def websocket_session(url):
        with pytest.raises(websockets.exceptions.InvalidStatusCode) as exc_info:
            async with websockets.client.connect(url):
                pass  # pragma: no cover
        assert exc_info.value.status_code == 404

    config = Config(
        app=app,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        await websocket_session(f"ws://127.0.0.1:{unused_tcp_port}")


@pytest.mark.anyio
async def test_server_multiple_websocket_http_response_start_events(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    """
    The server should raise an exception if it sends multiple
    websocket.http.response.start events.
    """
    exception_message: typing.Optional[str] = None

    async def app(scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable):
        nonlocal exception_message
        assert scope["type"] == "websocket"
        assert "extensions" in scope
        assert "websocket.http.response" in scope["extensions"]

        # Pull up first recv message.
        message = await receive()
        assert message["type"] == "websocket.connect"

        start_event: WebSocketResponseStartEvent = {
            "type": "websocket.http.response.start",
            "status": 404,
            "headers": [(b"Content-Length", b"0"), (b"Content-Type", b"text/plain")],
        }
        await send(start_event)
        try:
            await send(start_event)
        except Exception as exc:
            exception_message = str(exc)

    async def websocket_session(url: str):
        with pytest.raises(websockets.exceptions.InvalidStatusCode) as exc_info:
            async with websockets.client.connect(url):
                pass
        assert exc_info.value.status_code == 404

    config = Config(
        app=app,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        await websocket_session(f"ws://127.0.0.1:{unused_tcp_port}")

    assert exception_message == (
        "Expected ASGI message 'websocket.http.response.body' but got "
        "'websocket.http.response.start'."
    )


@pytest.mark.anyio
async def test_server_can_read_messages_in_buffer_after_close(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    frames = []
    disconnect_message = {}

    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send({"type": "websocket.accept"})
            # Ensure server doesn't start reading frames from read buffer until
            # after client has sent close frame, but server is still able to
            # read these frames
            await asyncio.sleep(0.2)

        async def websocket_disconnect(self, message):
            nonlocal disconnect_message
            disconnect_message = message

        async def websocket_receive(self, message):
            frames.append(message.get("bytes"))

    async def send_text(url: str):
        async with websockets.client.connect(url) as websocket:
            await websocket.send(b"abc")
            await websocket.send(b"abc")
            await websocket.send(b"abc")

    config = Config(
        app=App,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        await send_text(f"ws://127.0.0.1:{unused_tcp_port}")

    assert frames == [b"abc", b"abc", b"abc"]
    assert disconnect_message == {"type": "websocket.disconnect", "code": 1000}


@pytest.mark.anyio
async def test_default_server_headers(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send({"type": "websocket.accept"})

    async def open_connection(url: str):
        async with websockets.client.connect(url) as websocket:
            return websocket.response_headers

    config = Config(
        app=App,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        headers = await open_connection(f"ws://127.0.0.1:{unused_tcp_port}")
        assert headers.get("server") == "uvicorn" and "date" in headers


@pytest.mark.anyio
async def test_no_server_headers(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send({"type": "websocket.accept"})

    async def open_connection(url: str):
        async with websockets.client.connect(url) as websocket:
            return websocket.response_headers

    config = Config(
        app=App,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        server_header=False,
        port=unused_tcp_port,
    )
    async with run_server(config):
        headers = await open_connection(f"ws://127.0.0.1:{unused_tcp_port}")
        assert "server" not in headers


@pytest.mark.anyio
@skip_if_no_wsproto
async def test_no_date_header_on_wsproto(
    http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send({"type": "websocket.accept"})

    async def open_connection(url: str):
        async with websockets.client.connect(url) as websocket:
            return websocket.response_headers

    config = Config(
        app=App,
        ws=_WSProtocol,
        http=http_protocol_cls,
        lifespan="off",
        date_header=False,
        port=unused_tcp_port,
    )
    async with run_server(config):
        headers = await open_connection(f"ws://127.0.0.1:{unused_tcp_port}")
        assert "date" not in headers


@pytest.mark.anyio
async def test_multiple_server_header(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send(
                {
                    "type": "websocket.accept",
                    "headers": [
                        (b"Server", b"over-ridden"),
                        (b"Server", b"another-value"),
                    ],
                }
            )

    async def open_connection(url: str):
        async with websockets.client.connect(url) as websocket:
            return websocket.response_headers

    config = Config(
        app=App,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="off",
        port=unused_tcp_port,
    )
    async with run_server(config):
        headers = await open_connection(f"ws://127.0.0.1:{unused_tcp_port}")
        assert headers.get_all("Server") == ["uvicorn", "over-ridden", "another-value"]


@pytest.mark.anyio
async def test_lifespan_state(
    ws_protocol_cls: WSProtocol, http_protocol_cls: HTTPProtocol, unused_tcp_port: int
):
    expected_states = [
        {"a": 123, "b": [1]},
        {"a": 123, "b": [1, 2]},
    ]

    actual_states = []

    async def lifespan_app(
        scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ):
        message = await receive()
        assert message["type"] == "lifespan.startup" and "state" in scope
        scope["state"]["a"] = 123
        scope["state"]["b"] = [1]
        await send({"type": "lifespan.startup.complete"})
        message = await receive()
        assert message["type"] == "lifespan.shutdown"
        await send({"type": "lifespan.shutdown.complete"})

    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            actual_states.append(deepcopy(self.scope["state"]))
            self.scope["state"]["a"] = 456
            self.scope["state"]["b"].append(2)
            await self.send({"type": "websocket.accept"})

    async def open_connection(url: str):
        async with websockets.client.connect(url) as websocket:
            return websocket.open

    async def app_wrapper(
        scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ):
        if scope["type"] == "lifespan":
            return await lifespan_app(scope, receive, send)
        return await App(scope, receive, send)

    config = Config(
        app=app_wrapper,
        ws=ws_protocol_cls,
        http=http_protocol_cls,
        lifespan="on",
        port=unused_tcp_port,
    )
    async with run_server(config):
        is_open = await open_connection(f"ws://127.0.0.1:{unused_tcp_port}")
        assert is_open
        is_open = await open_connection(f"ws://127.0.0.1:{unused_tcp_port}")
        assert is_open

    assert expected_states == actual_states
