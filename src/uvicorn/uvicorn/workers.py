import uvloop
from gunicorn.workers.base import Worker

from uvicorn.config import Config
from uvicorn.main import Server


class UvicornWorker(Worker):
    """
    A worker class for Gunicorn that interfaces with an ASGI consumer callable,
    rather than a WSGI callable.
    """

    CONFIG_KWARGS = {"loop": "uvloop", "http": "httptools"}

    def run(self):
        self.log.level = self.log.loglevel
        kwargs = {
            "app": self.wsgi,
            "sockets": self.sockets,
            "logger": self.log,
            "timeout_keep_alive": self.cfg.keepalive,
            "timeout_notify": self.timeout,
            "callback_notify": self.callback_notify,
        }

        if self.cfg.is_ssl:
            _ssl_opt = {
                "ssl_keyfile": self.cfg.ssl_options.get("keyfile"),
                "ssl_certfile": self.cfg.ssl_options.get("certfile"),
                "ssl_version": self.cfg.ssl_options.get("ssl_version"),
                "ssl_cert_reqs": self.cfg.ssl_options.get("cert_reqs"),
                "ssl_ca_certs": self.cfg.ssl_options.get("ca_certs"),
                "ssl_ciphers": self.cfg.ssl_options.get("ciphers"),
            }
            kwargs.update(_ssl_opt)
        kwargs.update(self.CONFIG_KWARGS)
        self.config = Config(**kwargs)
        self.server = Server(config=self.config)
        self.server.run()

    def init_signals(self):
        pass

    async def callback_notify(self):
        self.notify()


class UvicornH11Worker(UvicornWorker):
    CONFIG_KWARGS = {"loop": "asyncio", "http": "h11"}
