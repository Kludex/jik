<p align="center">
  <a href="https://www.starlette.io/"><img width="320" height="192" src="https://raw.githubusercontent.com/encode/starlette/master/docs/starlette.png" alt='starlette'></a>
</p>
<p align="center">
    <em>✨ The little ASGI framework that shines. ✨</em>
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

**Documentation**: [https://www.starlette.io/](https://www.starlette.io/)

---

Starlette is a lightweight [ASGI](https://asgi.readthedocs.io/en/latest/) framework/toolkit,
which is ideal for building high performance asyncio services.

It is production-ready, and gives you the following:

* Seriously impressive performance.
* WebSocket support.
* GraphQL support.
* In-process background tasks.
* Startup and shutdown events.
* Test client built on `requests`.
* CORS, GZip, Static Files, Streaming responses.
* 100% test coverage.
* 100% type annotated codebase.
* Zero hard dependencies.

## Requirements

Python 3.6+

## Installation

```shell
$ pip3 install starlette
```

You'll also want to install an ASGI server, such as [uvicorn](http://www.uvicorn.org/), [daphne](https://github.com/django/daphne/), or [hypercorn](https://pgjones.gitlab.io/hypercorn/).

```shell
$ pip3 install uvicorn
```

## Example

```python
from starlette.applications import Starlette
from starlette.responses import JSONResponse
import uvicorn

app = Starlette()

@app.route('/')
async def homepage(request):
    return JSONResponse({'hello': 'world'})

if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000)
```

## Dependencies

Starlette does not have any hard dependencies, but the following are optional:

* `requests` - Required if you want to use the `TestClient`.
* `aiofiles` - Required if you want to use `FileResponse` or `StaticFiles`.
* `python-multipart` - Required if you want to support form parsing, with `request.form()`.
* `graphene` - Required for GraphQL support.
* `ujson` - Required if you want to use `UJSONResponse`.

You can install all of these with `pip3 install starlette[full]`.

## Framework or Toolkit

Starlette is designed to be used either as a complete framework, or as
an ASGI toolkit. You can use any of its components independently.

```python
from starlette.responses import PlainTextResponse


class App:
    def __init__(self, scope):
        self.scope = scope

    async def __call__(self, receive, send):
        response = PlainTextResponse('Hello, world!')
        await response(receive, send)
```

Run the `App` application in `example.py`:

```shell
$ uvicorn example:App
INFO: Started server process [11509]
INFO: Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

## Modularity

The modularity that Starlette is designed on promotes building re-usable
components that can be shared between any ASGI framework. This should enable
an ecosystem of shared middleware and mountable applications.

The clean API separation also means it's easier to understand each component
in isolation.

## Performance

Independent TechEmpower benchmarks show Starlette applications running under Uvicorn
as [one of the fastest Python frameworks available](https://www.techempower.com/benchmarks/#section=test&runid=14a815b6-93c1-4207-96bb-3960c29719e2&hw=ph&test=fortune&l=zijw1r-1&d=e3). *(\*)*

For high throughput loads you should:

* Make sure to install `ujson` and use `UJSONResponse`.
* Run using `uvicorn`, with access logging disabled.

Several of the ASGI servers also have pure Python implementations available,
so you can also run under `PyPy` if your application code has parts that are
CPU constrained.

Eg. `uvicorn.run(..., http='h11', loop='asyncio')`

*(\*) TechEmpower [continuous benchmarking results](https://tfb-status.techempower.com/), from 13th Sept 2018. Filtered to JavaScript, Python, and Ruby frameworks backed by Postgres, for comparision against similar candidates. To be updated to Round 17 once available.*

<p align="center">&mdash; ⭐️ &mdash;</p>
<p align="center"><i>Starlette is <a href="https://github.com/tomchristie/starlette/blob/master/LICENSE.md">BSD licensed</a> code. Designed & built in Brighton, England.</i></p>
