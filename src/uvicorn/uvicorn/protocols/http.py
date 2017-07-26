import asyncio
import collections
import email
import http
import httptools
import os
import time

from uvicorn.protocols.websocket import websocket_upgrade


def set_time_and_date():
    global CURRENT_TIME
    global DATE_HEADER

    CURRENT_TIME = time.time()
    DATE_HEADER = b''.join([
        b'date: ',
        email.utils.formatdate(CURRENT_TIME, usegmt=True).encode(),
        b'\r\n'
    ])


def get_status_line(status_code):
    try:
        phrase = http.HTTPStatus(status_code).phrase.encode()
    except ValueError:
        phrase = b''
    return b''.join([
        b'HTTP/1.1 ', str(status_code).encode(), b' ', phrase, b'\r\n'
    ])


CURRENT_TIME = 0.0
DATE_HEADER = b''
SERVER_HEADER = b'server: uvicorn\r\n'
STATUS_LINE = {
    status_code: get_status_line(status_code) for status_code in range(100, 600)
}

LOW_WATER_LIMIT = 16384
HIGH_WATER_LIMIT = 65536
MAX_PIPELINED_REQUESTS = 20

set_time_and_date()


class BodyChannel(object):
    __slots__ = ['_queue', '_protocol', '_released', 'name']

    def __init__(self, protocol):
        self._queue = asyncio.Queue()
        self._protocol = protocol
        self._released = False
        self.name = 'body:%d' % id(self)

    async def receive(self):
        """
        The public API for `channels['body']`.
        Returns a single HTTP body message.
        """
        message = await self._queue.get()
        self._protocol.buffer_size -= len(message['content'])
        self._protocol.check_resume_reading()
        return message

    def _put(self, message):
        """
        Body data messages are added syncronously.

        We keep track of the total amount of buffered body data,
        and pause reading if the total goes over the high water mark.
        """
        if self._released:
            return
        self._queue.put_nowait(message)
        self._protocol.buffer_size += len(message['content'])
        self._protocol.check_pause_reading()

    def _release(self):
        """
        Called once a response has been sent.

        Remove any remaining data from the buffer, and mark the stream as
        released so that it no longer buffers any input.
        """
        buffer_size = 0
        while not self._queue.empty():
            message = self._queue.get_nowait()
            buffer_size += len(message['content'])
        if buffer_size:
            self._protocol.buffer_size -= buffer_size
            self._protocol.check_resume_reading()
        self._released = True


class ReplyChannel(object):
    __slots__ = ['_protocol', '_use_chunked_encoding', '_should_keep_alive', 'name']

    def __init__(self, protocol):
        self._protocol = protocol
        self._use_chunked_encoding = False
        self._should_keep_alive = True
        self.name = 'reply:%d' % id(self)

    async def send(self, message):
        protocol = self._protocol
        transport = protocol.transport

        if transport is None:
            return

        if protocol.write_paused:
            await transport.drain()

        status = message.get('status')
        headers = message.get('headers', [])
        content = message.get('content', b'')
        more_content = message.get('more_content', False)

        if status is not None:
            response = [
                STATUS_LINE[status],
                SERVER_HEADER,
                DATE_HEADER,
            ]

            seen_content_length = False
            for header_name, header_value in headers:
                header = header_name.lower()
                if header == b'content-length':
                    seen_content_length = True
                elif header == b'connection':
                    if header_value.lower() == b'close':
                        self._should_keep_alive = False
                response.extend([header_name, b': ', header_value, b'\r\n'])

            if not seen_content_length:
                if more_content:
                    self._use_chunked_encoding = True
                    response.append(b'transfer-encoding: chunked\r\n')
                else:
                    response.extend([b'content-length: ', str(len(content)).encode(), b'\r\n'])

            response.append(b'\r\n')
            transport.write(b''.join(response))

        if content:
            if self._use_chunked_encoding:
                transport.write(b'%x\r\n' % len(content))
                transport.write(content)
                transport.write(b'\r\n')
            else:
                transport.write(content)

        if not more_content:
            if self._use_chunked_encoding:
                transport.write(b'0\r\n\r\n')
                self._use_chunked_encoding = False

            message, channels = protocol.active_request or ({}, {})
            if 'body' in channels:
                channels['body']._release()

            if not self._should_keep_alive or not protocol.request_parser.should_keep_alive():
                transport.close()
                protocol.transport = None
            elif protocol.pipeline_queue:
                message, channels = protocol.pipeline_queue.popleft()
                protocol.active_request = (message, channels)
                protocol.loop.create_task(protocol.consumer(message, channels))
                protocol.check_resume_reading()
            else:
                protocol.active_request = None

            protocol.state['total_requests'] += 1


class HttpProtocol(asyncio.Protocol):
    __slots__ = [
        'consumer', 'loop', 'request_parser', 'state',
        'base_message', 'base_channels',
        'transport', 'message', 'channels', 'headers', 'upgrade',
        'read_paused', 'write_paused',
        'buffer_size', 'high_water_limit', 'low_water_limit',
        'active_request', 'max_pipelined_requests', 'pipeline_queue'
    ]

    def __init__(self, consumer, loop=None, state=None):
        self.consumer = consumer
        self.loop = loop or asyncio.get_event_loop()
        self.request_parser = httptools.HttpRequestParser(self)
        if state is None:
            state = {'total_requests': 0}
        self.state = state

        self.base_message = {
            'channel': 'http.request'
        }
        self.base_channels = {
            'reply': ReplyChannel(self)
        }

        self.transport = None
        self.message = None
        self.channels = None
        self.headers = None
        self.upgrade = None

        self.read_paused = False
        self.write_paused = False

        self.buffer_size = 0
        self.high_water_limit = HIGH_WATER_LIMIT
        self.low_water_limit = LOW_WATER_LIMIT

        self.active_request = None
        self.max_pipelined_requests = MAX_PIPELINED_REQUESTS
        self.pipeline_queue = collections.deque()

    # The asyncio.Protocol hooks...
    def connection_made(self, transport):
        self.transport = transport
        self.base_message.update({
            'server': transport.get_extra_info('sockname'),
            'client': transport.get_extra_info('peername'),
            'scheme': 'https' if transport.get_extra_info('sslcontext') else 'http'
        })

    def connection_lost(self, exc):
        self.transport = None

    def eof_received(self):
        pass

    def data_received(self, data):
        try:
            self.request_parser.feed_data(data)
        except httptools.HttpParserUpgrade:
            websocket_upgrade(self)

    # Flow control...
    def pause_writing(self):
        self.write_paused = True

    def resume_writing(self):
        self.write_paused = False

    def check_pause_reading(self):
        if self.transport is None or self.read_paused:
            return
        if (self.buffer_size > self.high_water_limit or
            len(self.pipeline_queue) >= self.max_pipelined_requests):
            self.transport.pause_reading()
            self.read_paused = True

    def check_resume_reading(self):
        if self.transport is None or not self.read_paused:
            return
        if (self.buffer_size < self.low_water_limit and
            len(self.pipeline_queue) < self.max_pipelined_requests):
            self.transport.resume_reading()
            self.read_paused = False

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
        name = name.lower()
        if name == b'upgrade':
            self.upgrade = value
        elif name == b'expect' and value.lower() == b'100-continue':
            self.transport.write(b'HTTP/1.1 100 Continue\r\n\r\n')
        self.headers.append([name, value])

    def on_body(self, body: bytes):
        if 'body' not in self.channels:
            self.channels['body'] = BodyChannel(self)
            if self.active_request is None:
                self.loop.create_task(self.consumer(self.message, self.channels))
                self.active_request = (self.message, self.channels)
            else:
                self.pipeline_queue.append((self.message, self.channels))
                self.check_pause_reading()
        message = {
            'content': body,
            'more_content': True
        }
        self.channels['body']._put(message)

    def on_message_complete(self):
        if self.upgrade is not None:
            return

        if 'body' not in self.channels:
            if self.active_request is None:
                self.loop.create_task(self.consumer(self.message, self.channels))
                self.active_request = (self.message, self.channels)
            else:
                self.pipeline_queue.append((self.message, self.channels))
                self.check_pause_reading()
        else:
            message = {
                'content': b'',
                'more_content': False
            }
            self.channels['body']._put(message)
