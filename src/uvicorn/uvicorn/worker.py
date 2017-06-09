# wrk -d20s -t10 -c200 http://127.0.0.1:8080/
# gunicorn app:hello_world --bind localhost:8080 --worker-class worker.ASGIWorker
# https://github.com/MagicStack/httptools - Fast HTTP parsing.
# https://github.com/aio-libs/aiohttp - An asyncio framework, including gunicorn worker.
# https://github.com/channelcat/sanic - An asyncio framework, including gunicorn worker.
# https://python-hyper.org/projects/h2/en/stable/asyncio-example.html - HTTP2 parser
import asyncio
import email
import functools
import io
import os
import time

import httptools
import uvloop

from gunicorn.workers.base import Worker


CURRENT_TIME = time.time()
DATE_HEADER = b''.join([
    b'date: ',
    email.utils.formatdate(CURRENT_TIME, usegmt=True).encode(),
    b'\r\n'
])
SERVER_HEADER = b'server: uvicorn\r\n'
STATUS_LINE = {
    status_code: b''.join([b'HTTP/1.1 ', str(status_code).encode(), b'\r\n'])
    for status_code in range(200, 600)
}


class BodyChannel(object):
    __slots__ = ['_queue']

    def __init__(self):
        self._queue = asyncio.Queue()

    async def send(self, message):
        await self._queue.put(message)

    async def recieve(self):
        return await self._queue.get()


class ReplyChannel(object):
    __slots__ = ['_transport', '_keep_alive']

    def __init__(self, transport=None, keep_alive=True):
        self._transport = transport
        self._keep_alive = keep_alive

    async def send(self, message):
        status = message.get('status')
        headers = message.get('headers')
        content = message.get('content')
        more_content = message.get('more_content', False)

        if status is not None:
            response = [
                STATUS_LINE[status],
                SERVER_HEADER,
                DATE_HEADER,
            ]
            self._transport.write(b''.join(response))

        if headers is not None:
            if more_content:
                response = []
            else:
                response = [b'content-length: ', str(len(content)).encode(), b'\r\n']

            for header_name, header_value in headers:
                response.extend([header_name, b': ', header_value, b'\r\n'])
            response.append(b'\r\n')

            self._transport.write(b''.join(response))

        if content is not None:
            self._transport.write(content)

        if not more_content and not self._keep_alive:
            self._transport.close()


class HttpProtocol(asyncio.Protocol):
    __slots__ = [
        'consumer', 'loop', 'request_parser',
        'base_message', 'base_channels',
        'message', 'channels',
        'headers'
    ]

    def __init__(self, consumer, loop, sock, cfg):
        assert asyncio.iscoroutinefunction(consumer)
        self.consumer = consumer
        self.loop = loop
        self.request_parser = httptools.HttpRequestParser(self)

        self.base_message = {
            'scheme': 'https' if cfg.is_ssl else 'http',
            'root_path': os.environ.get('SCRIPT_NAME', ''),
            'server': sock.getsockname()
        }
        self.base_channels = None

        self.transport = None
        self.message = None
        self.headers = None

    # The asyncio.Protocol hooks...
    def connection_made(self, transport):
        self.base_channels = {
            'reply': ReplyChannel(transport)
        }

    def connection_lost(self, exc):
        pass

    def eof_received(self):
        pass

    def data_received(self, data):
        self.request_parser.feed_data(data)

    # Event hooks called back into by HttpRequestParser...
    def on_message_begin(self):
        self.message = self.base_message.copy()
        self.channels = self.base_channels.copy()
        self.headers = []

    def on_url(self, url):
        parsed = httptools.parse_url(url)
        method = self.request_parser.get_method()
        http_version = self.request_parser.get_http_version()
        self.message.update({
            'http_version': http_version,
            'method': method.decode('ascii'),
            'path': parsed.path.decode('ascii'),
            'query_string': parsed.query if parsed.query else b'',
            'headers': self.headers
        })

    def on_header(self, name: bytes, value: bytes):
        self.headers.append([name.lower(), value])

    def on_body(self, body: bytes):
        if 'body' not in self.channels:
            self.channels['body'] = BodyChannel()
            self.loop.create_task(self.consumer(self.message, self.channels))
        message = {
            'content': body,
            'more_content': True
        }
        self.loop.create_task(self.channels['body'].send(message))

    def on_message_complete(self):
        if not self.request_parser.should_keep_alive():
            self.channels['reply']._keep_alive = False

        if 'body' not in self.channels:
            self.loop.create_task(self.consumer(self.message, self.channels))
        else:
            message = {
                'content': b'',
                'more_content': False
            }
            self.loop.create_task(self.channels['body'].send(message))

    def on_chunk_header(self):
        pass

    def on_chunk_complete(self):
        pass


class UvicornWorker(Worker):
    """
    A worker class for Gunicorn that interfaces with an ASGI consumer callable,
    rather than a WSGI callable.

    We use a couple of packages from MagicStack in order to achieve an
    extremely high-throughput and low-latency implementation:

    * `uvloop` as the event loop policy.
    * `httptools` as the HTTP request parser.
    """

    def init_process(self):
        # Close any existing event loop before setting a
        # new policy.
        asyncio.get_event_loop().close()

        # Setup uvloop policy, so that every
        # asyncio.get_event_loop() will create an instance
        # of uvloop event loop.
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

        super().init_process()

    def run(self):
        loop = asyncio.get_event_loop()
        loop.create_task(self.create_servers(loop))
        loop.create_task(tick(loop, self.notify))
        loop.run_forever()

    async def create_servers(self, loop):
        cfg = self.cfg
        consumer = self.wsgi

        for sock in self.sockets:
            protocol = functools.partial(
                HttpProtocol,
                consumer=consumer, loop=loop, sock=sock, cfg=cfg
            )
            await loop.create_server(protocol, sock=sock)


async def tick(loop, notify):
    global CURRENT_TIME
    global DATE_HEADER

    cycle = 0
    while True:
        CURRENT_TIME = time.time()
        DATE_HEADER = b''.join([
            b'date: ',
            email.utils.formatdate(CURRENT_TIME, usegmt=True).encode(),
            b'\r\n'
        ])
        cycle = (cycle + 1) % 10
        if cycle == 0:
            notify()
        await asyncio.sleep(1)
