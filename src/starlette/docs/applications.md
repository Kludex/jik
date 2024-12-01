
Starlette includes an application class `Starlette` that nicely ties together all of
its other functionality.

```python
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route, Mount, WebSocketRoute
from starlette.staticfiles import StaticFiles


def homepage(request):
    return PlainTextResponse('Hello, world!')

def user_me(request):
    username = "John Doe"
    return PlainTextResponse('Hello, %s!' % username)

def user(request):
    username = request.path_params['username']
    return PlainTextResponse('Hello, %s!' % username)

async def websocket_endpoint(websocket):
    await websocket.accept()
    await websocket.send_text('Hello, websocket!')
    await websocket.close()

@asynccontextmanager
async def lifespan(app):
    print('Startup')
    yield
    print('Shutdown')


routes = [
    Route('/', homepage),
    Route('/user/me', user_me),
    Route('/user/{username}', user),
    WebSocketRoute('/ws', websocket_endpoint),
    Mount('/static', StaticFiles(directory="static")),
]

app = Starlette(debug=True, routes=routes, lifespan=lifespan)
```

??? abstract "API Reference"
    ::: starlette.applications.Starlette
        options:
            parameter_headings: false
            show_root_heading: true
            heading_level: 3
            filters:
                - "__init__"

### Storing state on the app instance

You can store arbitrary extra state on the application instance, using the
generic `app.state` attribute.

For example:

```python
app.state.ADMIN_EMAIL = 'admin@example.org'
```

### Accessing the app instance

Where a `request` is available (i.e. endpoints and middleware), the app is available on `request.app`.
