import asyncio
import enum
import collections
import email
import http
import httptools
import os
import time


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


class RequestResponseState(enum.Enum):
    STARTED = 0
    FINALIZING_HEADERS = 1
    SENDING_BODY = 2
    CLOSED = 3


class Request():
    def __init__(self, transport, scope, on_complete=None, keep_alive=True):
        self.state = RequestResponseState.STARTED
        self.transport = transport
        self.scope = scope
        self.on_complete = on_complete
        self.keep_alive = keep_alive
        self.chunked_encoding = False
        self.content_length = None
        self.receive_queue = asyncio.Queue()

    def put_message(self, message):
        if self.state == RequestResponseState.CLOSED:
            return
        self.receive_queue.put_nowait(message)

    async def receive(self):
        return await self.receive_queue.get()

    async def send(self, message):
        message_type = message['type']

        if message_type == 'http.response.start':
            if self.state != RequestResponseState.STARTED:
                raise Exception("Unexpected 'http.response.start' message.")

            status = message['status']
            headers = message.get('headers', [])

            content = [
                STATUS_LINE[status],
                SERVER_HEADER,
                DATE_HEADER,
            ]
            for header_name, header_value in headers:
                header = header_name.lower()
                if header == b'content-length':
                    self.content_length = int(header_value.decode())
                elif header == b'connection':
                    if header_value.lower() == b'close':
                        self.keep_alive = False
                content.extend([header_name, b': ', header_value, b'\r\n'])

            if self.content_length is None:
                self.state = RequestResponseState.FINALIZING_HEADERS
            else:
                content.append(b'\r\n')
                self.state = RequestResponseState.SENDING_BODY

            self.transport.write(b''.join(content))

        elif message_type == 'http.response.body':
            body = message.get('body', b'')
            more_body = message.get('more_body', False)

            if self.state == RequestResponseState.FINALIZING_HEADERS:
                if more_body:
                    content = [
                        b'transfer-encoding: chunked\r\n\r\n',
                        b'%x\r\n' % len(body),
                        body,
                        b'\r\n'
                    ]
                    self.chunked_encoding = True
                    self.transport.write(b''.join(content))
                else:
                    content = [
                        b'content-length: ',
                        str(len(body)).encode(),
                        b'\r\n\r\n',
                        body
                    ]
                    self.transport.write(b''.join(content))

            elif self.state == RequestResponseState.SENDING_BODY:
                if self.chunked_encoding:
                    content = [
                        b'%x\r\n' % len(body),
                        body,
                        b'\r\n'
                    ]
                    if not more_body:
                        content.append(b'0\r\n\r\n')
                    self.transport.write(b''.join(content))
                else:
                    self.transport.write(body)

            else:
                raise Exception("Unexpected 'http.response.body' message.")

            if more_body:
                self.state = RequestResponseState.SENDING_BODY
                return

            self.state = RequestResponseState.CLOSED

            if self.on_complete is not None:
                self.on_complete(keep_alive=self.keep_alive)


class HttpProtocol(asyncio.Protocol):
    def __init__(self, consumer, loop=None, state=None):
        self.consumer = consumer
        self.loop = loop or asyncio.get_event_loop()
        self.request_parser = httptools.HttpRequestParser(self)
        self.state = state or {'total_requests': 0}

        self.transport = None
        self.scope = None
        self.headers = []
        self.body = b''

        self.server = None
        self.client = None
        self.scheme = None

        # self.read_paused = False
        # self.write_paused = False

        # self.buffer_size = 0
        # self.high_water_limit = HIGH_WATER_LIMIT
        # self.low_water_limit = LOW_WATER_LIMIT

        # self.max_pipelined_requests = MAX_PIPELINED_REQUESTS
        self.pending_requests = collections.deque()
        self.active_request = None

    # The asyncio.Protocol hooks...
    def connection_made(self, transport):
        self.transport = transport
        self.server = transport.get_extra_info('sockname'),
        self.client = transport.get_extra_info('peername'),
        self.scheme = 'https' if transport.get_extra_info('sslcontext') else 'http'

    def connection_lost(self, exc):
        self.transport = None

    def eof_received(self):
        pass

    def data_received(self, data):
        try:
            self.request_parser.feed_data(data)
        except httptools.HttpParserUpgrade:
            self.close()

    # Event hooks called back into by HttpRequestParser...
    def on_message_begin(self):
        self.scope = None
        self.headers = []
        self.body = b''
        self.queue = None

    def on_url(self, url):
        parsed = httptools.parse_url(url)
        method = self.request_parser.get_method()
        http_version = self.request_parser.get_http_version()
        self.scope = {
            'type': 'http',
            'http_version': http_version,
            'server': self.server,
            'client': self.client,
            'scheme': self.scheme,
            'method': method.decode('ascii'),
            'path': parsed.path.decode('ascii'),
            'query_string': parsed.query if parsed.query else b'',
            'headers': self.headers
        }

    def on_header(self, name: bytes, value: bytes):
        self.headers.append([name.lower(), value])

    def on_headers_complete(self):
        if self.request_parser.should_upgrade():
            return

        request = Request(
            self.transport,
            self.scope,
            keep_alive=self.request_parser.should_keep_alive(),
            on_complete=self.on_response_complete
        )
        if self.active_request is None:
            self.active_request = request
            asgi_instance = self.consumer(request.scope)
            self.loop.create_task(asgi_instance(request.receive, request.send))
        else:
            self.pending_requests.append(request)
        self.body_queue = request.put_message

    def on_body(self, body: bytes):
        if self.body:
            self.body_queue({
                'type': 'http.request',
                'body': self.body,
                'more_body': True
            })
        self.body = body

    def on_message_complete(self):
        self.body_queue({
            'type': 'http.request',
            'body': self.body
        })

    # Called back into by RequestHandler
    def on_response_complete(self, keep_alive=True):
        self.state['total_requests'] += 1

        if not keep_alive:
            self.close()
            return

        if not self.pending_requests:
            self.active_request = None
            return

        request = self.pending_requests.popleft()
        self.active_request = request
        asgi_instance = self.consumer(request.scope)
        self.loop.create_task(asgi_instance(request.receive, request.send))

    def close(self):
        self.transport.close()
        self.active_request = None
        self.pending_requests.clear()
