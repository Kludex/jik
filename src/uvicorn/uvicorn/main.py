from uvicorn.debug import DebugMiddleware
from uvicorn.importer import import_from_string, ImportFromStringError
from uvicorn.reloaders.statreload import StatReload
import asyncio
import click
import signal
import os
import logging
import socket
import sys
import time
import multiprocessing


LOG_LEVELS = {
    "critical": logging.CRITICAL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
}
HTTP_PROTOCOLS = {
    "auto": "uvicorn.protocols.http.auto:AutoHTTPProtocol",
    "h11": "uvicorn.protocols.http.h11_impl:H11Protocol",
    "httptools": "uvicorn.protocols.http.httptools_impl:HttpToolsProtocol",
}
LOOP_SETUPS = {
    "auto": "uvicorn.loops.auto:auto_loop_setup",
    "asyncio": "uvicorn.loops.asyncio:asyncio_setup",
    "uvloop": "uvicorn.loops.uvloop:uvloop_setup",
}

LEVEL_CHOICES = click.Choice(LOG_LEVELS.keys())
HTTP_CHOICES = click.Choice(HTTP_PROTOCOLS.keys())
LOOP_CHOICES = click.Choice(LOOP_SETUPS.keys())

HANDLED_SIGNALS = (
    signal.SIGINT,  # Unix signal 2. Sent by Ctrl+C.
    signal.SIGTERM,  # Unix signal 15. Sent by `kill <pid>`.
)


def get_logger(log_level):
    log_level = LOG_LEVELS[log_level]
    logging.basicConfig(format="%(levelname)s: %(message)s", level=log_level)
    return logging.getLogger()


@click.command()
@click.argument("app")
@click.option("--host", type=str, default="127.0.0.1", help="Bind socket to this host.")
@click.option("--port", type=int, default=8000, help="Bind socket to this port.")
@click.option("--uds", type=str, default=None, help="Bind to a UNIX domain socket.")
@click.option(
    "--fd", type=int, default=None, help="Bind to socket from this file descriptor."
)
@click.option(
    "--loop", type=LOOP_CHOICES, default="auto", help="Event loop implementation."
)
@click.option(
    "--http", type=HTTP_CHOICES, default="auto", help="HTTP parser implementation."
)
@click.option("--debug", is_flag=True, default=False, help="Enable debug mode.")
@click.option("--log-level", type=LEVEL_CHOICES, default="info", help="Log level.")
@click.option(
    "--proxy-headers",
    is_flag=True,
    default=False,
    help="Use X-Forwarded-Proto, X-Forwarded-For, X-Forwarded-Port to populate remote address info.",
)
@click.option(
    "--root-path",
    type=str,
    default="",
    help="Set the ASGI 'root_path' for applications submounted below a given URL path.",
)
def main(
    app,
    host: str,
    port: int,
    uds: str,
    fd: int,
    loop: str,
    http: str,
    debug: bool,
    log_level: str,
    proxy_headers: bool,
    root_path: str,
):
    sys.path.insert(0, ".")

    kwargs = {
        "app": app,
        "host": host,
        "port": port,
        "uds": uds,
        "fd": fd,
        "loop": loop,
        "http": http,
        "log_level": log_level,
        "debug": debug,
        "proxy_headers": proxy_headers,
        "root_path": root_path,
    }

    if debug:
        logger = get_logger(log_level)
        reloader = StatReload(logger)
        reloader.run(run, kwargs)
    else:
        run(**kwargs)


def run(
    app,
    host="127.0.0.1",
    port=8000,
    uds=None,
    fd=None,
    loop="auto",
    http="auto",
    log_level="info",
    debug=False,
    proxy_headers=False,
    root_path="",
):
    try:
        app = import_from_string(app)
    except ImportFromStringError as exc:
        click.echo("Error loading ASGI app. %s" % exc)
        sys.exit(1)

    if debug:
        app = DebugMiddleware(app)

    if fd is None:
        sock = None
    else:
        host = None
        port = None
        sock = socket.fromfd(fd, socket.AF_UNIX, socket.SOCK_STREAM)

    logger = get_logger(log_level)
    loop_setup = import_from_string(LOOP_SETUPS[loop])
    protocol_class = import_from_string(HTTP_PROTOCOLS[http])

    loop = loop_setup()

    def create_protocol():
        return protocol_class(
            app=app,
            loop=loop,
            logger=logger,
            proxy_headers=proxy_headers,
            root_path=root_path,
        )

    server = Server(
        app=app,
        host=host,
        port=port,
        uds=uds,
        sock=sock,
        logger=logger,
        loop=loop,
        create_protocol=create_protocol,
        on_tick=protocol_class.tick,
    )
    server.run()


class Server:
    def __init__(
        self, app, host, port, uds, sock, logger, loop, create_protocol, on_tick
    ):
        self.app = app
        self.host = host
        self.port = port
        self.uds = uds
        self.sock = sock
        self.logger = logger
        self.loop = loop
        self.create_protocol = create_protocol
        self.on_tick = on_tick
        self.should_exit = False
        self.pid = os.getpid()

    def set_signal_handlers(self):
        try:
            for sig in HANDLED_SIGNALS:
                self.loop.add_signal_handler(sig, self.handle_exit, sig, None)
        except NotImplementedError:
            # Windows
            for sig in HANDLED_SIGNALS:
                signal.signal(sig, self.handle_exit)

    def handle_exit(self, sig, frame):
        self.should_exit = True

    def run(self):
        self.logger.info("Started server process [{}]".format(self.pid))
        self.set_signal_handlers()
        self.loop.run_until_complete(self.create_server())
        self.loop.create_task(self.tick())
        self.loop.run_forever()

    async def create_server(self):
        if self.sock is not None:
            # Use an existing socket.
            self.server = await self.loop.create_server(
                self.create_protocol, sock=self.sock
            )
            message = "* Uvicorn running on socket %s 🦄 (Press CTRL+C to quit)"
            click.echo(message % str(self.sock.getsockname()))

        elif self.uds is not None:
            # Create a socket using UNIX domain socket.
            self.server = await self.loop.create_unix_server(
                self.create_protocol, path=self.uds
            )
            message = "* Uvicorn running on socket %s 🦄 (Press CTRL+C to quit)"
            click.echo(message % self.uds)

        else:
            # Standard case. Create a socket from a host/port pair.
            self.server = await self.loop.create_server(
                self.create_protocol, host=self.host, port=self.port
            )
            message = "* Uvicorn running on http://%s:%d 🦄 (Press CTRL+C to quit)"
            click.echo(message % (self.host, self.port))

    async def tick(self):
        while not self.should_exit:
            self.on_tick()
            await asyncio.sleep(1)

        self.logger.info("Stopping server process [{}]".format(self.pid))
        self.server.close()
        await self.server.wait_closed()
        self.loop.stop()


if __name__ == "__main__":
    main()
