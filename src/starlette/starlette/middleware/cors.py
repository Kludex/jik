from starlette.datastructures import Headers, MutableHeaders, URL
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, ASGIInstance, Scope
import functools
import typing


ALL_METHODS = ("DELETE", "GET", "OPTIONS", "PATCH", "POST", "PUT")


class CORSMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        allow_origins: typing.Sequence[str] = (),
        allow_methods: typing.Sequence[str] = ("GET",),
        allow_headers: typing.Sequence[str] = (),
        allow_credentials: bool = False,
        expose_headers: typing.Sequence[str] = (),
        max_age: int = 600,
    ):

        if "*" in allow_methods:
            allow_methods = ALL_METHODS

        simple_headers = {}
        if "*" in allow_origins:
            simple_headers["Access-Control-Allow-Origin"] = "*"
        if allow_credentials:
            simple_headers["Access-Control-Allow-Credentials"] = "true"
        if expose_headers:
            simple_headers["Access-Control-Expose-Headers"] = ", ".join(expose_headers)

        preflight_headers = {}
        if "*" in allow_origins:
            preflight_headers["Access-Control-Allow-Origin"] = "*"
        else:
            preflight_headers["Vary"] = "Origin"
        preflight_headers.update(
            {
                "Access-Control-Allow-Methods": ", ".join(allow_methods),
                "Access-Control-Max-Age": str(max_age),
            }
        )
        if allow_headers and "*" not in allow_headers:
            preflight_headers["Access-Control-Allow-Headers"] = ", ".join(allow_headers)
        if allow_credentials:
            preflight_headers["Access-Control-Allow-Credentials"] = "true"

        self.app = app
        self.allow_origins = allow_origins
        self.allow_methods = allow_methods
        self.allow_headers = allow_headers
        self.allow_all_origins = "*" in allow_origins
        self.allow_all_headers = "*" in allow_headers
        self.simple_headers = simple_headers
        self.preflight_headers = preflight_headers

    def __call__(self, scope: Scope):
        if scope["type"] == "http":
            method = scope["method"]
            headers = Headers(scope["headers"])
            origin = headers.get("origin")

            if origin is not None:
                if method == "OPTIONS" and "access-control-request-method" in headers:
                    return self.preflight_response(request_headers=headers)
                else:
                    return functools.partial(
                        self.simple_response, scope=scope, origin=origin
                    )

        return self.app(scope)

    def preflight_response(self, request_headers):
        requested_origin = request_headers["origin"]
        requested_method = request_headers["access-control-request-method"]
        requested_headers = request_headers.get("access-control-request-headers")
        requested_cookie = "cookie" in request_headers

        headers = dict(self.preflight_headers)
        failures = []

        # If we only allow specific origins, then we have to mirror back
        # the Origin header in the response.
        if not self.allow_all_origins:
            if requested_origin in self.allow_origins:
                headers["Access-Control-Allow-Origin"] = requested_origin
            else:
                failures.append("origin")

        if requested_method not in self.allow_methods:
            failures.append("method")

        # If we allow all headers, then we have to mirror back any requested
        # headers in the response.
        if self.allow_all_headers and requested_headers is not None:
            headers["Access-Control-Allow-Headers"] = requested_headers
        elif requested_headers is not None:
            for header in requested_headers.split(","):
                if header.strip() not in self.allow_headers:
                    failures.append("headers")

        # We don't strictly need to use 400 responses here, since its up to
        # the browser to enforce the CORS policy, but its more informative
        # if we do.
        if failures:
            failure_text = "Disallowed CORS " + ", ".join(failures)
            return PlainTextResponse(failure_text, status_code=400, headers=headers)

        return PlainTextResponse("OK", status_code=200, headers=headers)

    async def simple_response(self, receive, send, scope=None, origin=None):
        inner = self.app(scope)
        send = functools.partial(self.send, send=send, origin=origin)
        await inner(receive, send)

    async def send(self, message, send=None, origin=None):
        if message["type"] != "http.response.start":
            await send(message)

        message.setdefault("headers", [])
        headers = MutableHeaders(message["headers"])

        # If we only allow specific origins, then we have to mirror back
        # the Origin header in the response.
        if not self.allow_all_origins and origin in self.allow_origins:
            headers["Access-Control-Allow-Origin"] = origin
        headers.update(self.simple_headers)
        await send(message)
