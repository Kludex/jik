import asyncio

import pytest

from uvicorn.config import Config
from uvicorn.lifespan.off import LifespanOff
from uvicorn.lifespan.on import LifespanOn


def test_lifespan_on():
    startup_complete = False
    shutdown_complete = False

    async def app(scope, receive, send):
        nonlocal startup_complete, shutdown_complete
        message = await receive()
        assert message["type"] == "lifespan.startup"
        startup_complete = True
        await send({"type": "lifespan.startup.complete"})
        message = await receive()
        assert message["type"] == "lifespan.shutdown"
        shutdown_complete = True
        await send({"type": "lifespan.shutdown.complete"})

    async def test():
        config = Config(app=app, lifespan="on")
        lifespan = LifespanOn(config)

        assert not startup_complete
        assert not shutdown_complete
        await lifespan.startup()
        assert startup_complete
        assert not shutdown_complete
        await lifespan.shutdown()
        assert startup_complete
        assert shutdown_complete

    loop = asyncio.new_event_loop()
    loop.run_until_complete(test())


def test_lifespan_off():
    async def app(scope, receive, send):
        pass  # pragma: no cover

    async def test():
        config = Config(app=app, lifespan="off")
        lifespan = LifespanOff(config)

        await lifespan.startup()
        await lifespan.shutdown()

    loop = asyncio.new_event_loop()
    loop.run_until_complete(test())


def test_lifespan_auto():
    startup_complete = False
    shutdown_complete = False

    async def app(scope, receive, send):
        nonlocal startup_complete, shutdown_complete
        message = await receive()
        assert message["type"] == "lifespan.startup"
        startup_complete = True
        await send({"type": "lifespan.startup.complete"})
        message = await receive()
        assert message["type"] == "lifespan.shutdown"
        shutdown_complete = True
        await send({"type": "lifespan.shutdown.complete"})

    async def test():
        config = Config(app=app, lifespan="auto")
        lifespan = LifespanOn(config)

        assert not startup_complete
        assert not shutdown_complete
        await lifespan.startup()
        assert startup_complete
        assert not shutdown_complete
        await lifespan.shutdown()
        assert startup_complete
        assert shutdown_complete

    loop = asyncio.new_event_loop()
    loop.run_until_complete(test())


def test_lifespan_auto_with_error():
    async def app(scope, receive, send):
        assert scope["type"] == "http"

    async def test():
        config = Config(app=app, lifespan="auto")
        lifespan = LifespanOn(config)

        await lifespan.startup()
        assert lifespan.error_occured
        assert not lifespan.should_exit
        await lifespan.shutdown()

    loop = asyncio.new_event_loop()
    loop.run_until_complete(test())


def test_lifespan_on_with_error():
    async def app(scope, receive, send):
        if scope["type"] != "http":
            raise RuntimeError()

    async def test():
        config = Config(app=app, lifespan="on")
        lifespan = LifespanOn(config)

        await lifespan.startup()
        assert lifespan.error_occured
        assert lifespan.should_exit
        await lifespan.shutdown()

    loop = asyncio.new_event_loop()
    loop.run_until_complete(test())


@pytest.mark.parametrize("mode", ("auto", "on"))
def test_lifespan_with_failed_startup(mode):
    async def app(scope, receive, send):
        message = await receive()
        assert message["type"] == "lifespan.startup"
        exc = RuntimeError("Failed")
        await send({"type": "lifespan.startup.failed", "message": str(exc)})
        raise exc

    async def test():
        config = Config(app=app, lifespan=mode)
        lifespan = LifespanOn(config)

        await lifespan.startup()
        assert lifespan.error_occured
        assert lifespan.should_exit
        await lifespan.shutdown()

    loop = asyncio.new_event_loop()
    loop.run_until_complete(test())
