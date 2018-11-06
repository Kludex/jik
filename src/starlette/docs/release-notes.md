## 0.7.2

### Middleware

* Add support for `@app.middleware("http")` decorator.

### Routing

* Add "endpoint" to ASGI scope.

## 0.7.1

### Debug tracebacks

* Improve debug traceback information & styling.

### URL routing

* Support mounted URL lookups with "path=", eg. `url_for('static', path=...)`.
* Support nested URL lookups, eg. `url_for('admin:user', username=...)`.
* Add redirect slashes support.
* Add www redirect support.

### Background tasks

* Add background task support to `FileResponse` and `StreamingResponse`.

## 0.7.0

### API Schema support

* Add `app.schema_generator = SchemaGenerator(...)`.
* Add `app.schema` property.
* Add `OpenAPIResponse(...)`.

### GraphQL routing

* Drop `app.add_graphql_route("/", ...)` in favor of more consistent `app.add_route("/", GraphQLApp(...))`.

## 0.6.3

### Routing API

* Support routing to methods.
* Ensure `url_path_for` works with Mount('/{some_path_params}').
* Fix Router(default=) argument.
* Support repeated paths, like: `@app.route("/", methods=["GET"])`, `@app.route("/", methods=["POST"])`
* Use the default ThreadPoolExecutor for all sync endpoints.

## 0.6.2

### SessionMiddleware

Added support for `request.session`, with `SessionMiddleware`.

## 0.6.1

### BaseHTTPMiddleware

Added support for `BaseHTTPMiddleware`, which provides a standard
request/response interface over a regular ASGI middleware.

This means you can write ASGI middleware while still working at
a request/response level, rather than handling ASGI messages directly.

```python
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware


class CustomMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers['Custom-Header'] = 'Example'
        return response


app = Starlette()
app.add_middleware(CustomMiddleware)
```

## 0.6.0

### request.path_params

The biggest change in 0.6 is that endpoint signatures are no longer:

```python
async def func(request: Request, **kwargs) -> Response
```

Instead we just use:

```python
async def func(request: Request) -> Response
```

The path parameters are available on the request as `request.path_params`.

This is different to most Python webframeworks, but I think it actually ends up
being much more nicely consistent all the way through.

### request.url_for()

Request and WebSocketSession now support URL reversing with `request.url_for(name, **path_params)`.
This method returns a fully qualified `URL` instance.
The URL instance is a string-like object.

### app.url_path_for()

Applications now support URL path reversing with `app.url_path_for(name, **path_params)`.
This method returns a `URL` instance with the path and scheme set.
The URL instance is a string-like object, and will return only the path if coerced to a string.

### app.routes

Applications now support a `.routes` parameter, which returns a list of `[Route|WebSocketRoute|Mount]`.

### Route, WebSocketRoute, Mount

The low level components to `Router` now match the `@app.route()`, `@app.websocket_route()`, and `app.mount()` signatures.
