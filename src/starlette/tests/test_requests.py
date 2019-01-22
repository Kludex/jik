import asyncio

import pytest

from starlette.requests import ClientDisconnect, Request
from starlette.responses import JSONResponse, Response
from starlette.testclient import TestClient


def test_request_url():
    def app(scope):
        async def asgi(receive, send):
            request = Request(scope, receive)
            data = {"method": request.method, "url": str(request.url)}
            response = JSONResponse(data)
            await response(receive, send)

        return asgi

    client = TestClient(app)
    response = client.get("/123?a=abc")
    assert response.json() == {"method": "GET", "url": "http://testserver/123?a=abc"}

    response = client.get("https://example.org:123/")
    assert response.json() == {"method": "GET", "url": "https://example.org:123/"}


def test_request_query_params():
    def app(scope):
        async def asgi(receive, send):
            request = Request(scope, receive)
            params = dict(request.query_params)
            response = JSONResponse({"params": params})
            await response(receive, send)

        return asgi

    client = TestClient(app)
    response = client.get("/?a=123&b=456")
    assert response.json() == {"params": {"a": "123", "b": "456"}}


def test_request_headers():
    def app(scope):
        async def asgi(receive, send):
            request = Request(scope, receive)
            headers = dict(request.headers)
            response = JSONResponse({"headers": headers})
            await response(receive, send)

        return asgi

    client = TestClient(app)
    response = client.get("/", headers={"host": "example.org"})
    assert response.json() == {
        "headers": {
            "host": "example.org",
            "user-agent": "testclient",
            "accept-encoding": "gzip, deflate",
            "accept": "*/*",
            "connection": "keep-alive",
        }
    }


def test_request_client():
    def app(scope):
        async def asgi(receive, send):
            request = Request(scope, receive)
            response = JSONResponse(
                {"host": request.client.host, "port": request.client.port}
            )
            await response(receive, send)

        return asgi

    client = TestClient(app)
    response = client.get("/")
    assert response.json() == {"host": "testclient", "port": 50000}


def test_request_body():
    def app(scope):
        async def asgi(receive, send):
            request = Request(scope, receive)
            body = await request.body()
            response = JSONResponse({"body": body.decode()})
            await response(receive, send)

        return asgi

    client = TestClient(app)

    response = client.get("/")
    assert response.json() == {"body": ""}

    response = client.post("/", json={"a": "123"})
    assert response.json() == {"body": '{"a": "123"}'}

    response = client.post("/", data="abc")
    assert response.json() == {"body": "abc"}


def test_request_stream():
    def app(scope):
        async def asgi(receive, send):
            request = Request(scope, receive)
            body = b""
            async for chunk in request.stream():
                body += chunk
            response = JSONResponse({"body": body.decode()})
            await response(receive, send)

        return asgi

    client = TestClient(app)

    response = client.get("/")
    assert response.json() == {"body": ""}

    response = client.post("/", json={"a": "123"})
    assert response.json() == {"body": '{"a": "123"}'}

    response = client.post("/", data="abc")
    assert response.json() == {"body": "abc"}


def test_request_form_urlencoded():
    def app(scope):
        async def asgi(receive, send):
            request = Request(scope, receive)
            form = await request.form()
            response = JSONResponse({"form": dict(form)})
            await response(receive, send)

        return asgi

    client = TestClient(app)

    response = client.post("/", data={"abc": "123 @"})
    assert response.json() == {"form": {"abc": "123 @"}}


def test_request_body_then_stream():
    def app(scope):
        async def asgi(receive, send):
            request = Request(scope, receive)
            body = await request.body()
            chunks = b""
            async for chunk in request.stream():
                chunks += chunk
            response = JSONResponse({"body": body.decode(), "stream": chunks.decode()})
            await response(receive, send)

        return asgi

    client = TestClient(app)

    response = client.post("/", data="abc")
    assert response.json() == {"body": "abc", "stream": "abc"}


def test_request_stream_then_body():
    def app(scope):
        async def asgi(receive, send):
            request = Request(scope, receive)
            chunks = b""
            async for chunk in request.stream():
                chunks += chunk
            try:
                body = await request.body()
            except RuntimeError:
                body = b"<stream consumed>"
            response = JSONResponse({"body": body.decode(), "stream": chunks.decode()})
            await response(receive, send)

        return asgi

    client = TestClient(app)

    response = client.post("/", data="abc")
    assert response.json() == {"body": "<stream consumed>", "stream": "abc"}


def test_request_json():
    def app(scope):
        async def asgi(receive, send):
            request = Request(scope, receive)
            data = await request.json()
            response = JSONResponse({"json": data})
            await response(receive, send)

        return asgi

    client = TestClient(app)
    response = client.post("/", json={"a": "123"})
    assert response.json() == {"json": {"a": "123"}}


def test_request_scope_interface():
    """
    A Request can be instantiated with a scope, and presents a `Mapping`
    interface.
    """
    request = Request({"type": "http", "method": "GET", "path": "/abc/"})
    assert request["method"] == "GET"
    assert dict(request) == {"type": "http", "method": "GET", "path": "/abc/"}
    assert len(request) == 3


def test_request_without_setting_receive():
    """
    If Request is instantiated without the receive channel, then .body()
    is not available.
    """

    def app(scope):
        async def asgi(receive, send):
            request = Request(scope)
            try:
                data = await request.json()
            except RuntimeError:
                data = "Receive channel not available"
            response = JSONResponse({"json": data})
            await response(receive, send)

        return asgi

    client = TestClient(app)
    response = client.post("/", json={"a": "123"})
    assert response.json() == {"json": "Receive channel not available"}


def test_request_disconnect():
    """
    If a client disconnect occurs while reading request body
    then ClientDisconnect should be raised.
    """

    def app(scope):
        async def asgi(receive, send):
            request = Request(scope, receive)
            await request.body()

        return asgi

    async def receiver():
        return {"type": "http.disconnect"}

    scope = {"type": "http", "method": "POST", "path": "/"}
    asgi_callable = app(scope)
    loop = asyncio.get_event_loop()
    with pytest.raises(ClientDisconnect):
        loop.run_until_complete(asgi_callable(receiver, None))


def test_request_is_disconnected():
    """
    If a client disconnect occurs while reading request body
    then ClientDisconnect should be raised.
    """
    disconnected_after_response = None

    def app(scope):
        async def asgi(receive, send):
            nonlocal disconnected_after_response

            request = Request(scope, receive)
            await request.body()
            disconnected = await request.is_disconnected()
            response = JSONResponse({"disconnected": disconnected})
            await response(receive, send)
            disconnected_after_response = await request.is_disconnected()

        return asgi

    client = TestClient(app)
    response = client.get("/")
    assert response.json() == {"disconnected": False}
    assert disconnected_after_response


def test_request_cookies():
    def app(scope):
        async def asgi(receive, send):
            request = Request(scope, receive)
            mycookie = request.cookies.get("mycookie")
            if mycookie:
                response = Response(mycookie, media_type="text/plain")
            else:
                response = Response("Hello, world!", media_type="text/plain")
                response.set_cookie("mycookie", "Hello, cookies!")

            await response(receive, send)

        return asgi

    client = TestClient(app)
    response = client.get("/")
    assert response.text == "Hello, world!"
    response = client.get("/")
    assert response.text == "Hello, cookies!"


def test_chunked_encoding():
    def app(scope):
        async def asgi(receive, send):
            request = Request(scope, receive)
            body = await request.body()
            response = JSONResponse({"body": body.decode()})
            await response(receive, send)

        return asgi

    client = TestClient(app)

    def post_body():
        yield b"foo"
        yield "bar"

    response = client.post("/", data=post_body())
    assert response.json() == {"body": "foobar"}
