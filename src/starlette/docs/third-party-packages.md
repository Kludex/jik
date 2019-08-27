
Starlette has a rapidly growing community of developers, building tools that integrate into Starlette, tools that depend on Starlette, etc.

Here are some of those third party packages:


## Backports

### Python 3.5 port

<a href="https://github.com/em92/starlette" target="_blank">GitHub</a>

## Plugins

### Starlette APISpec

<a href="https://github.com/Woile/starlette-apispec" target="_blank">GitHub</a>

Simple APISpec integration for Starlette.
Document your REST API built with Starlette by declaring OpenAPI (Swagger)
schemas in YAML format in your endpoint's docstrings.

### webargs-starlette

<a href="https://github.com/sloria/webargs-starlette" target="_blank">GitHub</a>

Declarative request parsing and validation for Starlette, built on top
of [webargs](https://github.com/marshmallow-code/webargs).

Allows you to parse querystring, JSON, form, headers, and cookies using
type annotations.

### Mangum

<a href="https://github.com/erm/mangum" target="_blank">GitHub</a>

Serverless ASGI adapter for AWS Lambda & API Gateway.

### Nejma

<a href="https://github.com/taoufik07/nejma" target="_blank">GitHub</a>

Manage and send messages to groups of channels using websockets.
Checkout <a href="https://github.com/taoufik07/nejma-chat" target="_blank">nejma-chat</a>, a simple chat application built using `nejma` and `starlette`.

### Starlette Prometheus

<a href="https://github.com/perdy/starlette-prometheus" target="_blank">GitHub</a>

A plugin for providing an endpoint that exposes [Prometheus](https://prometheus.io/) metrics based on its [official python client](https://github.com/prometheus/client_python).

## Frameworks

### Responder

<a href="https://github.com/kennethreitz/responder" target="_blank">GitHub</a> |
<a href="https://python-responder.org/en/latest/" target="_blank">Documentation</a>

Async web service framework. Some Features: flask-style route expression,
yaml support, OpenAPI schema generation, background tasks, graphql.

### FastAPI

<a href="https://github.com/tiangolo/fastapi" target="_blank">GitHub</a> |
<a href="https://fastapi.tiangolo.com/" target="_blank">Documentation</a>

High performance, easy to learn, fast to code, ready for production web API framework.
Inspired by **APIStar**'s previous server system with type declarations for route parameters, based on the OpenAPI specification version 3.0.0+ (with JSON Schema), powered by **Pydantic** for the data handling.

### Bocadillo

<a href="https://github.com/bocadilloproject/bocadillo" target="_blank">GitHub</a> |
<a href="https://bocadilloproject.github.io" target="_blank">Documentation</a>

A modern Python web framework filled with asynchronous salsa.
Bocadillo is **async-first** and designed with productivity and simplicity in mind. It is not meant to be minimal: a **carefully chosen set of included batteries** helps you build performant web apps and services with minimal setup.

### Flama

<a href="https://github.com/perdy/flama/" target="_blank">GitHub</a> |
<a href="https://flama.perdy.io/" target="_blank">Documentation</a>

Formerly Starlette API.

Flama aims to bring a layer on top of Starlette to provide an **easy to learn** and **fast to develop** approach for building **highly performant** GraphQL and REST APIs. In the same way of Starlette is, Flama is a perfect option for developing **asynchronous** and **production-ready** services.