from uvicorn.protocols.http.h11_impl import H11Protocol
from uvicorn.protocols.http.httptools_impl import HttpToolsProtocol
import asyncio
import h11
import pytest


class Response:
    charset = "utf-8"

    def __init__(self, content, status_code=200, headers=None, media_type=None):
        self.body = self.render(content)
        self.status_code = status_code
        self.headers = headers or {}
        self.media_type = media_type
        self.set_content_type()
        self.set_content_length()

    async def __call__(self, receive, send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": [
                    [key.encode(), value.encode()]
                    for key, value in self.headers.items()
                ],
            }
        )
        await send({"type": "http.response.body", "body": self.body})

    def render(self, content) -> bytes:
        if isinstance(content, bytes):
            return content
        return content.encode(self.charset)

    def set_content_length(self):
        if "content-length" not in self.headers:
            self.headers["content-length"] = str(len(self.body))

    def set_content_type(self):
        if self.media_type is not None and "content-type" not in self.headers:
            content_type = self.media_type
            if content_type.startswith("text/") and self.charset is not None:
                content_type += "; charset=%s" % self.charset
            self.headers["content-type"] = content_type


SIMPLE_GET_REQUEST = b"\r\n".join([b"GET / HTTP/1.1", b"Host: example.org", b"", b""])

SIMPLE_POST_REQUEST = b"\r\n".join(
    [
        b"POST / HTTP/1.1",
        b"Host: example.org",
        b"Content-Type: application/json",
        b"Content-Length: 18",
        b"",
        b'{"hello": "world"}',
    ]
)

LARGE_POST_REQUEST = b"\r\n".join(
    [
        b"POST / HTTP/1.1",
        b"Host: example.org",
        b"Content-Type: text/plain",
        b"Content-Length: 100000",
        b"",
        b"x" * 100000,
    ]
)

START_POST_REQUEST = b"\r\n".join(
    [
        b"POST / HTTP/1.1",
        b"Host: example.org",
        b"Content-Type: application/json",
        b"Content-Length: 18",
        b"",
        b"",
    ]
)

FINISH_POST_REQUEST = b'{"hello": "world"}'


HTTP10_GET_REQUEST = b"\r\n".join([b"GET / HTTP/1.0", b"Host: example.org", b"", b""])


class MockTransport:
    def __init__(self, sockname=None, peername=None, sslcontext=False):
        self.sockname = ("127.0.0.1", 8000) if sockname is None else sockname
        self.peername = ("127.0.0.1", 8001) if peername is None else peername
        self.sslcontext = sslcontext
        self.closed = False
        self.buffer = b""
        self.read_paused = False

    def get_extra_info(self, key):
        return {
            "sockname": self.sockname,
            "peername": self.peername,
            "sslcontext": self.sslcontext,
        }[key]

    def write(self, data):
        assert not self.closed
        self.buffer += data

    def close(self):
        assert not self.closed
        self.closed = True

    def pause_reading(self):
        self.read_paused = True

    def resume_reading(self):
        self.read_paused = False

    def is_closing(self):
        return self.closed

    def clear_buffer(self):
        self.buffer = b""


class MockLoop:
    def __init__(self):
        self.tasks = []
        self.later = []

    def create_task(self, coroutine):
        self.tasks.insert(0, coroutine)

    def call_later(self, delay, callback):
        self.later.insert(0, (delay, callback))
        return MockHandle()

    def run_one(self):
        coroutine = self.tasks.pop()
        asyncio.get_event_loop().run_until_complete(coroutine)

    def run_later(self, with_delay):
        later = []
        for delay, callback in self.later:
            if with_delay >= delay:
                callback()
            else:
                later.append((delay, coroutine))
        self.later = later


class MockHandle:
    def cancel(self):
        pass


def get_connected_protocol(app, protocol_cls, **kwargs):
    loop = MockLoop()
    transport = MockTransport()
    protocol = protocol_cls(app, loop, **kwargs)
    protocol.connection_made(transport)
    return protocol


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_get_request(protocol_cls):
    def app(scope):
        return Response("Hello, world", media_type="text/plain")

    protocol = get_connected_protocol(app, protocol_cls)
    protocol.data_received(SIMPLE_GET_REQUEST)
    protocol.loop.run_one()
    assert b"HTTP/1.1 200 OK" in protocol.transport.buffer
    assert b"Hello, world" in protocol.transport.buffer


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_post_request(protocol_cls):
    class App:
        def __init__(self, scope):
            self.scope = scope

        async def __call__(self, receive, send):
            body = b""
            more_body = True
            while more_body:
                message = await receive()
                body += message.get("body", b"")
                more_body = message.get("more_body", False)
            response = Response(b"Body: " + body, media_type="text/plain")
            await response(receive, send)

    protocol = get_connected_protocol(App, protocol_cls)
    protocol.data_received(SIMPLE_POST_REQUEST)
    protocol.loop.run_one()
    assert b"HTTP/1.1 200 OK" in protocol.transport.buffer
    assert b'Body: {"hello": "world"}' in protocol.transport.buffer


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_keepalive(protocol_cls):
    def app(scope):
        return Response(b"", status_code=204)

    protocol = get_connected_protocol(app, protocol_cls)

    protocol.data_received(SIMPLE_GET_REQUEST)
    protocol.loop.run_one()
    assert b"HTTP/1.1 204 No Content" in protocol.transport.buffer
    assert not protocol.transport.is_closing()


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_keepalive_timeout(protocol_cls):
    def app(scope):
        return Response(b"", status_code=204)

    protocol = get_connected_protocol(app, protocol_cls)

    protocol.data_received(SIMPLE_GET_REQUEST)
    protocol.loop.run_one()
    assert b"HTTP/1.1 204 No Content" in protocol.transport.buffer
    assert not protocol.transport.is_closing()

    protocol.loop.run_later(with_delay=10)
    assert protocol.transport.is_closing()


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_close(protocol_cls):
    def app(scope):
        return Response(b"", status_code=204, headers={"connection": "close"})

    protocol = get_connected_protocol(app, protocol_cls)
    protocol.data_received(SIMPLE_GET_REQUEST)
    protocol.loop.run_one()
    assert b"HTTP/1.1 204 No Content" in protocol.transport.buffer
    assert protocol.transport.is_closing()


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_chunked_encoding(protocol_cls):
    def app(scope):
        return Response(
            b"Hello, world!", status_code=200, headers={"transfer-encoding": "chunked"}
        )

    protocol = get_connected_protocol(app, protocol_cls)
    protocol.data_received(SIMPLE_GET_REQUEST)
    protocol.loop.run_one()
    assert b"HTTP/1.1 200 OK" in protocol.transport.buffer
    assert b"0\r\n\r\n" in protocol.transport.buffer
    assert not protocol.transport.is_closing()


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_pipelined_requests(protocol_cls):
    def app(scope):
        return Response("Hello, world", media_type="text/plain")

    protocol = get_connected_protocol(app, protocol_cls)
    protocol.data_received(SIMPLE_GET_REQUEST)
    protocol.data_received(SIMPLE_GET_REQUEST)
    protocol.data_received(SIMPLE_GET_REQUEST)

    protocol.loop.run_one()
    assert b"HTTP/1.1 200 OK" in protocol.transport.buffer
    assert b"Hello, world" in protocol.transport.buffer
    protocol.transport.clear_buffer()

    protocol.loop.run_one()
    assert b"HTTP/1.1 200 OK" in protocol.transport.buffer
    assert b"Hello, world" in protocol.transport.buffer
    protocol.transport.clear_buffer()

    protocol.loop.run_one()
    assert b"HTTP/1.1 200 OK" in protocol.transport.buffer
    assert b"Hello, world" in protocol.transport.buffer
    protocol.transport.clear_buffer()


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_undersized_request(protocol_cls):
    def app(scope):
        return Response(b"xxx", headers={"content-length": "10"})

    protocol = get_connected_protocol(app, protocol_cls)
    protocol.data_received(SIMPLE_GET_REQUEST)
    protocol.loop.run_one()
    assert protocol.transport.is_closing()


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_oversized_request(protocol_cls):
    def app(scope):
        return Response(b"xxx" * 20, headers={"content-length": "10"})

    protocol = get_connected_protocol(app, protocol_cls)
    protocol.data_received(SIMPLE_GET_REQUEST)
    protocol.loop.run_one()
    assert protocol.transport.is_closing()


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_large_post_request(protocol_cls):
    def app(scope):
        return Response("Hello, world", media_type="text/plain")

    protocol = get_connected_protocol(app, protocol_cls)
    protocol.data_received(LARGE_POST_REQUEST)
    assert protocol.transport.read_paused
    protocol.loop.run_one()
    assert not protocol.transport.read_paused


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_invalid_http(protocol_cls):
    app = lambda scope: None
    protocol = get_connected_protocol(app, protocol_cls)
    protocol.data_received(b"x" * 100000)
    assert protocol.transport.is_closing()


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_app_exception(protocol_cls):
    class App:
        def __init__(self, scope):
            self.scope = scope

        async def __call__(self, receive, send):
            raise Exception()

    protocol = get_connected_protocol(App, protocol_cls)
    protocol.data_received(SIMPLE_GET_REQUEST)
    protocol.loop.run_one()
    assert b"HTTP/1.1 500 Internal Server Error" in protocol.transport.buffer
    assert protocol.transport.is_closing()


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_app_init_exception(protocol_cls):
    def app(scope):
        raise Exception()

    protocol = get_connected_protocol(app, protocol_cls)
    protocol.data_received(SIMPLE_GET_REQUEST)
    protocol.loop.run_one()
    assert b"HTTP/1.1 500 Internal Server Error" in protocol.transport.buffer
    assert protocol.transport.is_closing()


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_exception_during_response(protocol_cls):
    class App:
        def __init__(self, scope):
            pass

        async def __call__(self, receive, send):
            await send({"type": "http.response.start", "status": 200})
            await send({"type": "http.response.body", "body": b"1", "more_body": True})
            raise Exception()

    protocol = get_connected_protocol(App, protocol_cls)
    protocol.data_received(SIMPLE_GET_REQUEST)
    protocol.loop.run_one()
    assert b"HTTP/1.1 500 Internal Server Error" not in protocol.transport.buffer
    assert protocol.transport.is_closing()


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_no_response_returned(protocol_cls):
    class App:
        def __init__(self, scope):
            pass

        async def __call__(self, receive, send):
            pass

    protocol = get_connected_protocol(App, protocol_cls)
    protocol.data_received(SIMPLE_GET_REQUEST)
    protocol.loop.run_one()
    assert b"HTTP/1.1 500 Internal Server Error" in protocol.transport.buffer
    assert protocol.transport.is_closing()


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_partial_response_returned(protocol_cls):
    class App:
        def __init__(self, scope):
            pass

        async def __call__(self, receive, send):
            await send({"type": "http.response.start", "status": 200})

    protocol = get_connected_protocol(App, protocol_cls)
    protocol.data_received(SIMPLE_GET_REQUEST)
    protocol.loop.run_one()
    assert b"HTTP/1.1 500 Internal Server Error" not in protocol.transport.buffer
    assert protocol.transport.is_closing()


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_duplicate_start_message(protocol_cls):
    class App:
        def __init__(self, scope):
            pass

        async def __call__(self, receive, send):
            await send({"type": "http.response.start", "status": 200})
            await send({"type": "http.response.start", "status": 200})

    protocol = get_connected_protocol(App, protocol_cls)
    protocol.data_received(SIMPLE_GET_REQUEST)
    protocol.loop.run_one()
    assert b"HTTP/1.1 500 Internal Server Error" not in protocol.transport.buffer
    assert protocol.transport.is_closing()


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_missing_start_message(protocol_cls):
    class App:
        def __init__(self, scope):
            pass

        async def __call__(self, receive, send):
            await send({"type": "http.response.body", "body": b""})

    protocol = get_connected_protocol(App, protocol_cls)
    protocol.data_received(SIMPLE_GET_REQUEST)
    protocol.loop.run_one()
    assert b"HTTP/1.1 500 Internal Server Error" in protocol.transport.buffer
    assert protocol.transport.is_closing()


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_message_after_body_complete(protocol_cls):
    class App:
        def __init__(self, scope):
            pass

        async def __call__(self, receive, send):
            await send({"type": "http.response.start", "status": 200})
            await send({"type": "http.response.body", "body": b""})
            await send({"type": "http.response.body", "body": b""})

    protocol = get_connected_protocol(App, protocol_cls)
    protocol.data_received(SIMPLE_GET_REQUEST)
    protocol.loop.run_one()
    assert b"HTTP/1.1 200 OK" in protocol.transport.buffer
    assert protocol.transport.is_closing()


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_value_returned(protocol_cls):
    class App:
        def __init__(self, scope):
            pass

        async def __call__(self, receive, send):
            await send({"type": "http.response.start", "status": 200})
            await send({"type": "http.response.body", "body": b""})
            return 123

    protocol = get_connected_protocol(App, protocol_cls)
    protocol.data_received(SIMPLE_GET_REQUEST)
    protocol.loop.run_one()
    assert b"HTTP/1.1 200 OK" in protocol.transport.buffer
    assert protocol.transport.is_closing()


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_early_disconnect(protocol_cls):
    got_disconnect_event = False

    class App:
        def __init__(self, scope):
            pass

        async def __call__(self, receive, send):
            nonlocal got_disconnect_event

            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    break

            got_disconnect_event = True

    protocol = get_connected_protocol(App, protocol_cls)
    protocol.data_received(SIMPLE_POST_REQUEST)
    protocol.eof_received()
    protocol.connection_lost(None)
    protocol.loop.run_one()
    assert got_disconnect_event


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_early_response(protocol_cls):
    def app(scope):
        return Response("Hello, world", media_type="text/plain")

    protocol = get_connected_protocol(app, protocol_cls)
    protocol.data_received(START_POST_REQUEST)
    protocol.loop.run_one()
    assert b"HTTP/1.1 200 OK" in protocol.transport.buffer
    protocol.data_received(FINISH_POST_REQUEST)
    assert not protocol.transport.is_closing()


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_read_after_response(protocol_cls):
    message_after_response = None

    class App:
        def __init__(self, scope):
            pass

        async def __call__(self, receive, send):
            nonlocal message_after_response

            response = Response("Hello, world", media_type="text/plain")
            await response(receive, send)
            message_after_response = await receive()

    protocol = get_connected_protocol(App, protocol_cls)
    protocol.data_received(SIMPLE_POST_REQUEST)
    protocol.loop.run_one()
    assert b"HTTP/1.1 200 OK" in protocol.transport.buffer
    assert message_after_response == {"type": "http.disconnect"}


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_http10_request(protocol_cls):
    def app(scope):
        content = "Version: %s" % scope["http_version"]
        return Response(content, media_type="text/plain")

    protocol = get_connected_protocol(app, protocol_cls)
    protocol.data_received(HTTP10_GET_REQUEST)
    protocol.loop.run_one()
    assert b"HTTP/1.1 200 OK" in protocol.transport.buffer
    assert b"Version: 1.0" in protocol.transport.buffer


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_root_path(protocol_cls):
    def app(scope):
        path = scope.get("root_path", "") + scope["path"]
        return Response("Path: " + path, media_type="text/plain")

    protocol = get_connected_protocol(app, protocol_cls, root_path="/app")
    protocol.data_received(SIMPLE_GET_REQUEST)
    protocol.loop.run_one()
    assert b"HTTP/1.1 200 OK" in protocol.transport.buffer
    assert b"Path: /app/" in protocol.transport.buffer


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_proxy_headers(protocol_cls):
    def app(scope):
        scheme = scope["scheme"]
        host, port = scope["client"]
        addr = "%s://%s:%d" % (scheme, host, port)
        return Response("Remote: " + addr, media_type="text/plain")

    REQUEST = b"\r\n".join(
        [
            b"GET / HTTP/1.1",
            b"Host: example.org",
            b"X-Forwarded-Proto: https",
            b"X-Forwarded-For: 1.2.3.4",
            b"X-Forwarded-Port: 567",
            b"",
            b"",
        ]
    )
    protocol = get_connected_protocol(app, protocol_cls, proxy_headers=True)
    protocol.data_received(REQUEST)
    protocol.loop.run_one()
    assert b"HTTP/1.1 200 OK" in protocol.transport.buffer
    assert b"Remote: https://1.2.3.4:567" in protocol.transport.buffer


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_max_connections(protocol_cls):
    app = lambda scope: None
    protocol = get_connected_protocol(app, protocol_cls, max_connections=1)
    protocol.data_received(SIMPLE_GET_REQUEST)
    protocol.loop.run_one()
    assert b"HTTP/1.1 503 Service Unavailable" in protocol.transport.buffer


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_shutdown_during_request(protocol_cls):
    def app(scope):
        return Response(b"", status_code=204)

    protocol = get_connected_protocol(app, protocol_cls)
    protocol.data_received(SIMPLE_GET_REQUEST)
    protocol.shutdown()
    protocol.loop.run_one()
    assert b"HTTP/1.1 204 No Content" in protocol.transport.buffer
    assert protocol.transport.is_closing()


@pytest.mark.parametrize("protocol_cls", [HttpToolsProtocol, H11Protocol])
def test_shutdown_during_idle(protocol_cls):
    app = lambda scope: None
    protocol = get_connected_protocol(app, protocol_cls)
    protocol.shutdown()
    assert protocol.transport.buffer == b""
    assert protocol.transport.is_closing()
