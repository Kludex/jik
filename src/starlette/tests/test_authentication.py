from __future__ import annotations

import base64
import binascii
from typing import Any, Awaitable, Callable
from urllib.parse import urlencode

import pytest

from starlette.applications import Starlette
from starlette.authentication import (
    AuthCredentials,
    AuthenticationBackend,
    AuthenticationError,
    SimpleUser,
    requires,
)
from starlette.endpoints import HTTPEndpoint
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import HTTPConnection, Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect

TestClientFactory = Callable[..., TestClient]
AsyncEndpoint = Callable[..., Awaitable[Response]]
SyncEndpoint = Callable[..., Response]


class BasicAuth(AuthenticationBackend):
    async def authenticate(
        self,
        request: HTTPConnection,
    ) -> tuple[AuthCredentials, SimpleUser] | None:
        if "Authorization" not in request.headers:
            return None

        auth = request.headers["Authorization"]
        try:
            scheme, credentials = auth.split()
            decoded = base64.b64decode(credentials).decode("ascii")
        except (ValueError, UnicodeDecodeError, binascii.Error):
            raise AuthenticationError("Invalid basic auth credentials")

        username, _, password = decoded.partition(":")
        return AuthCredentials(["authenticated"]), SimpleUser(username)


def homepage(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "authenticated": request.user.is_authenticated,
            "user": request.user.display_name,
        }
    )


@requires("authenticated")
async def dashboard(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "authenticated": request.user.is_authenticated,
            "user": request.user.display_name,
        }
    )


@requires("authenticated", redirect="homepage")
async def admin(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "authenticated": request.user.is_authenticated,
            "user": request.user.display_name,
        }
    )


@requires("authenticated")
def dashboard_sync(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "authenticated": request.user.is_authenticated,
            "user": request.user.display_name,
        }
    )


class Dashboard(HTTPEndpoint):
    @requires("authenticated")
    def get(self, request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "authenticated": request.user.is_authenticated,
                "user": request.user.display_name,
            }
        )


@requires("authenticated", redirect="homepage")
def admin_sync(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "authenticated": request.user.is_authenticated,
            "user": request.user.display_name,
        }
    )


@requires("authenticated")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json(
        {
            "authenticated": websocket.user.is_authenticated,
            "user": websocket.user.display_name,
        }
    )


def async_inject_decorator(
    **kwargs: Any,
) -> Callable[[AsyncEndpoint], Callable[..., Awaitable[Response]]]:
    def wrapper(endpoint: AsyncEndpoint) -> Callable[..., Awaitable[Response]]:
        async def app(request: Request) -> Response:
            return await endpoint(request=request, **kwargs)

        return app

    return wrapper


@async_inject_decorator(additional="payload")
@requires("authenticated")
async def decorated_async(request: Request, additional: str) -> JSONResponse:
    return JSONResponse(
        {
            "authenticated": request.user.is_authenticated,
            "user": request.user.display_name,
            "additional": additional,
        }
    )


def sync_inject_decorator(
    **kwargs: Any,
) -> Callable[[SyncEndpoint], Callable[..., Response]]:
    def wrapper(endpoint: SyncEndpoint) -> Callable[..., Response]:
        def app(request: Request) -> Response:
            return endpoint(request=request, **kwargs)

        return app

    return wrapper


@sync_inject_decorator(additional="payload")
@requires("authenticated")
def decorated_sync(request: Request, additional: str) -> JSONResponse:
    return JSONResponse(
        {
            "authenticated": request.user.is_authenticated,
            "user": request.user.display_name,
            "additional": additional,
        }
    )


def ws_inject_decorator(**kwargs: Any) -> Callable[..., AsyncEndpoint]:
    def wrapper(endpoint: AsyncEndpoint) -> AsyncEndpoint:
        def app(websocket: WebSocket) -> Awaitable[Response]:
            return endpoint(websocket=websocket, **kwargs)

        return app

    return wrapper


@ws_inject_decorator(additional="payload")
@requires("authenticated")
async def websocket_endpoint_decorated(websocket: WebSocket, additional: str) -> None:
    await websocket.accept()
    await websocket.send_json(
        {
            "authenticated": websocket.user.is_authenticated,
            "user": websocket.user.display_name,
            "additional": additional,
        }
    )


app = Starlette(
    middleware=[Middleware(AuthenticationMiddleware, backend=BasicAuth())],
    routes=[
        Route("/", endpoint=homepage),
        Route("/dashboard", endpoint=dashboard),
        Route("/admin", endpoint=admin),
        Route("/dashboard/sync", endpoint=dashboard_sync),
        Route("/dashboard/class", endpoint=Dashboard),
        Route("/admin/sync", endpoint=admin_sync),
        Route("/dashboard/decorated", endpoint=decorated_async),
        Route("/dashboard/decorated/sync", endpoint=decorated_sync),
        WebSocketRoute("/ws", endpoint=websocket_endpoint),
        WebSocketRoute("/ws/decorated", endpoint=websocket_endpoint_decorated),
    ],
)


def test_invalid_decorator_usage() -> None:
    with pytest.raises(Exception):

        @requires("authenticated")
        def foo() -> None:
            pass  # pragma: nocover


def test_user_interface(test_client_factory: TestClientFactory) -> None:
    with test_client_factory(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.json() == {"authenticated": False, "user": ""}

        response = client.get("/", auth=("tomchristie", "example"))
        assert response.status_code == 200
        assert response.json() == {"authenticated": True, "user": "tomchristie"}


def test_authentication_required(test_client_factory: TestClientFactory) -> None:
    with test_client_factory(app) as client:
        response = client.get("/dashboard")
        assert response.status_code == 403

        response = client.get("/dashboard", auth=("tomchristie", "example"))
        assert response.status_code == 200
        assert response.json() == {"authenticated": True, "user": "tomchristie"}

        response = client.get("/dashboard/sync")
        assert response.status_code == 403

        response = client.get("/dashboard/sync", auth=("tomchristie", "example"))
        assert response.status_code == 200
        assert response.json() == {"authenticated": True, "user": "tomchristie"}

        response = client.get("/dashboard/class")
        assert response.status_code == 403

        response = client.get("/dashboard/class", auth=("tomchristie", "example"))
        assert response.status_code == 200
        assert response.json() == {"authenticated": True, "user": "tomchristie"}

        response = client.get("/dashboard/decorated", auth=("tomchristie", "example"))
        assert response.status_code == 200
        assert response.json() == {
            "authenticated": True,
            "user": "tomchristie",
            "additional": "payload",
        }

        response = client.get("/dashboard/decorated")
        assert response.status_code == 403

        response = client.get(
            "/dashboard/decorated/sync", auth=("tomchristie", "example")
        )
        assert response.status_code == 200
        assert response.json() == {
            "authenticated": True,
            "user": "tomchristie",
            "additional": "payload",
        }

        response = client.get("/dashboard/decorated/sync")
        assert response.status_code == 403

        response = client.get("/dashboard", headers={"Authorization": "basic foobar"})
        assert response.status_code == 400
        assert response.text == "Invalid basic auth credentials"


def test_websocket_authentication_required(
    test_client_factory: TestClientFactory,
) -> None:
    with test_client_factory(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws"):
                pass  # pragma: nocover

        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/ws", headers={"Authorization": "basic foobar"}
            ):
                pass  # pragma: nocover

        with client.websocket_connect(
            "/ws", auth=("tomchristie", "example")
        ) as websocket:
            data = websocket.receive_json()
            assert data == {"authenticated": True, "user": "tomchristie"}

        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/decorated"):
                pass  # pragma: nocover

        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/ws/decorated", headers={"Authorization": "basic foobar"}
            ):
                pass  # pragma: nocover

        with client.websocket_connect(
            "/ws/decorated", auth=("tomchristie", "example")
        ) as websocket:
            data = websocket.receive_json()
            assert data == {
                "authenticated": True,
                "user": "tomchristie",
                "additional": "payload",
            }


def test_authentication_redirect(test_client_factory: TestClientFactory) -> None:
    with test_client_factory(app) as client:
        response = client.get("/admin")
        assert response.status_code == 200
        url = "{}?{}".format(
            "http://testserver/", urlencode({"next": "http://testserver/admin"})
        )
        assert response.url == url

        response = client.get("/admin", auth=("tomchristie", "example"))
        assert response.status_code == 200
        assert response.json() == {"authenticated": True, "user": "tomchristie"}

        response = client.get("/admin/sync")
        assert response.status_code == 200
        url = "{}?{}".format(
            "http://testserver/", urlencode({"next": "http://testserver/admin/sync"})
        )
        assert response.url == url

        response = client.get("/admin/sync", auth=("tomchristie", "example"))
        assert response.status_code == 200
        assert response.json() == {"authenticated": True, "user": "tomchristie"}


def on_auth_error(request: HTTPConnection, exc: AuthenticationError) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=401)


@requires("authenticated")
def control_panel(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "authenticated": request.user.is_authenticated,
            "user": request.user.display_name,
        }
    )


other_app = Starlette(
    routes=[Route("/control-panel", control_panel)],
    middleware=[
        Middleware(
            AuthenticationMiddleware, backend=BasicAuth(), on_error=on_auth_error
        )
    ],
)


def test_custom_on_error(test_client_factory: TestClientFactory) -> None:
    with test_client_factory(other_app) as client:
        response = client.get("/control-panel", auth=("tomchristie", "example"))
        assert response.status_code == 200
        assert response.json() == {"authenticated": True, "user": "tomchristie"}

        response = client.get(
            "/control-panel", headers={"Authorization": "basic foobar"}
        )
        assert response.status_code == 401
        assert response.json() == {"error": "Invalid basic auth credentials"}
