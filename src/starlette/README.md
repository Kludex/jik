<h1 align="center">
    Starlette
</h1>
<p align="center">
    <em>The little ASGI library that shines.</em>
</p>
<p align="center">
<a href="https://travis-ci.org/encode/starlette">
    <img src="https://travis-ci.org/encode/starlette.svg?branch=master" alt="Build Status">
</a>
<a href="https://codecov.io/gh/encode/starlette">
    <img src="https://codecov.io/gh/encode/starlette/branch/master/graph/badge.svg" alt="Coverage">
</a>
<a href="https://pypi.org/project/starlette/">
    <img src="https://badge.fury.io/py/starlette.svg" alt="Package version">
</a>
</p>

---

Starlette is a small library for working with ASGI.

It gives you `Request` and `Response` classes, a test client, and a
decorator for writing super-minimal applications.

**Installation:**

```shell
pip3 install starlette
```

**Example:**

```python
from starlette import Response


class App:
    def __init__(self, scope):
        self.scope = scope

    async def __call__(self, receive, send):
        response = Response('Hello, world!', media_type='text/plain')
        await response(receive, send)
```

You can run the application with any ASGI server, including [uvicorn](http://www.uvicorn.org/), [daphne](https://github.com/django/daphne/), or [hypercorn](https://pgjones.gitlab.io/hypercorn/),

<p align="center">&mdash; ⭐️ &mdash;</p>

## Responses

Starlette includes a few response classes that handle sending back the
appropriate ASGI messages on the `send` channel.

### Response

Signature: `Response(content=b'', status_code=200, headers=None, media_type=None)`

* `content` - A string or bytestring.
* `status_code` - An integer HTTP status code.
* `headers` - A dictionary of strings or list of pairs of strings.
* `media_type` - A string giving the content type.

Starlette will automatically include a content-length header. It will also
set the content-type header, including a charset for text types.

```python
class App:
    def __init__(self, scope):
        self.scope = scope

    async def __call__(self, receive, send):
        response = Response('Hello, world!', media_type='text/plain')
        await response(receive, send)
```

### HTMLResponse

Takes some text or bytes and returns an HTML response.

```python
from starlette import HTMLResponse


class App:
    def __init__(self, scope):
        self.scope = scope

    async def __call__(self, receive, send):
        response = HTMLResponse('<html><body><h1>Hello, world!</h1></body></html')
        await response(receive, send)
```

### JSONResponse

Takes some data and returns an `application/json` encoded response.

```python
from starlette import JSONResponse


class App:
    def __init__(self, scope):
        self.scope = scope

    async def __call__(self, receive, send):
        response = JSONResponse({'hello': 'world'})
        await response(receive, send)
```

### StreamingResponse

Takes an async generator and streams the response body.

```python
from starlette import Request, StreamingResponse
import asyncio


async def slow_numbers(minimum, maximum):
    yield('<html><body><ul>')
    for number in range(minimum, maximum + 1):
        yield '<li>%d</li>' % number
        await asyncio.sleep(0.5)
    yield('</ul></body></html>')


class App:
    def __init__(self, scope):
        self.scope = scope

    async def __call__(self, receive, send):
        generator = slow_numbers(1, 10)
        response = StreamingResponse(generator, media_type='text/html')
        await response(receive, send)
```

---

## Requests

Starlette includes a `Request` class that gives you a nicer interface onto
the incoming request, rather than accessing the ASGI scope and receive channel directly.

### Request

Signature: `Request(scope, receive)`

```python
class App:
    def __init__(self, scope):
        self.scope = scope

    async def __call__(self, receive, send):
        request = Request(self.scope, receive)
        content = '%s %s' % (request.method, request.url.path)
        response = Response(content, media_type='text/plain')
        await response(receive, send)
```

### Method

The request method is accessed as `request.method`.

#### URL

The request URL is accessed as `request.url`.

The property is actually a subclass of `str`, and also exposes all the
components that can be parsed out of the URL.

For example: `request.url.path`, `request.url.port`, `request.url.scheme`.

#### Headers

Headers are exposed as an immutable, case-insensitive, multi-dict.

For example: `request.headers['content-type']`

#### Query Parameters

Headers are exposed as an immutable multi-dict.

For example: `request.query_params['abc']`

#### Body

There are two interfaces for returning the body of the request:

The request body as bytes: `await request.body()`

The request body, parsed as JSON: `await request.json()`

---

## Test Client

The test client allows you to make requests against your ASGI application,
using the `requests` library.

```python
from starlette import HTMLResponse, TestClient


class App:
    def __init__(self, scope):
        self.scope = scope

    async def __call__(self, receive, send):
        response = HTMLResponse('<html><body>Hello, world!</body></html>')
        await response(receive, send)


def test_app():
    client = TestClient(App)
    response = client.get('/')
    assert response.status_code == 200
```

---

## Decorators

The `asgi_application` decorator turns an `async` function into an ASGI application.

The function must take a single `request` argument, and return a response.

```python
from starlette import asgi_application, HTMLResponse


@asgi_application
async def app(request):
    return HTMLResponse('<html><body>Hello, world!</body></html>')
```

---

<p align="center"><i>API Star is <a href="https://github.com/tomchristie/apistar/blob/master/LICENSE.md">BSD licensed</a> code.<br/>Designed & built in Brighton, England.</i><br/>&mdash; ⭐️ &mdash;</p>
