# Deployment

Server deployment is a complex area, that will depend on what kind of service you're deploying Uvicorn onto.

As a general rule, you probably want to:

* Run `uvicorn --debug` from the command line for local development.
* Run `gunicorn -k uvicorn.workers.UvicornWorker` for production.
* Additionally run behind Nginx for self-hosted deployments.
* Finally, run everything behind a CDN for caching support, and serious DDOS protection.

## Running from the command line

Typically you'll run `uvicorn` from the command line.

```
$ uvicorn app:App --debug --port 5000
```

The ASGI application should be specified in the form `path.to.module:instance.path`.

When running locally, use `--debug` to turn on auto-reloading, and display error tracebacks in the browser.

To see the complete set of available options, use `uvicorn --help`:

```
$ uvicorn --help
Usage: uvicorn [OPTIONS] APP

Options:
  --host TEXT                     Bind socket to this host.  [default:
                                  127.0.0.1]
  --port INTEGER                  Bind socket to this port.  [default: 8000]
  --uds TEXT                      Bind to a UNIX domain socket.
  --fd INTEGER                    Bind to socket from this file descriptor.
  --loop [auto|asyncio|uvloop]    Event loop implementation.  [default: auto]
  --http [auto|h11|httptools]     HTTP parser implementation.  [default: auto]
  --ws [none|auto|websockets|wsproto]
                                  WebSocket protocol implementation.
                                  [default: auto]
  --wsgi                          Use WSGI as the application interface,
                                  instead of ASGI.
  --debug                         Enable debug mode.
  --log-level [critical|error|warning|info|debug]
                                  Log level.  [default: info]
  --proxy-headers                 Use X-Forwarded-Proto, X-Forwarded-For,
                                  X-Forwarded-Port to populate remote address
                                  info.
  --root-path TEXT                Set the ASGI 'root_path' for applications
                                  submounted below a given URL path.
  --limit-concurrency INTEGER     Maximum number of concurrent connections or
                                  tasks to allow, before issuing HTTP 503
                                  responses.
  --limit-max-requests INTEGER    Maximum number of requests to service before
                                  terminating the process.
  --timeout-keep-alive INTEGER    Close Keep-Alive connections if no new data
                                  is received within this timeout.  [default:
                                  5]
  --help                          Show this message and exit.
```

See the [settings documentation](settings.md) for more details on the supported options for running uvicorn.

## Running programmatically

To run directly from within a Python program, you should use `uvicorn.run(app, **config)`. For example:

```python
import uvicorn

class App:
    ...

if __name__ == "__main__":
    uvicorn.run(App, host="127.0.0.1", port=5000, log_level="info", debug=True)
```

The set of configuration options is the same as for the command line tool.

There are a couple of extra things to be aware of:

* The reloader is not enabled when running programmatically.
* Running programatically always just uses a single process.

## Using a process manager

Running Uvicorn using a process manager ensures that you can run multiple processes in a resiliant manner, and allows you to perform server upgrades without dropping requests.

A process manager will handle the socket setup, start-up multiple server processes, monitor process aliveness, and listen for signals to provide for processes restarts, shutdowns, or dialing up and down the number of running processes.

It is possible that a future version of Uvicorn might build in multiple-worker support and process management, but it is currently being treated as out-of-scope, given the existing tools that already deal with this comprehensivly.

### Gunicorn

Gunicorn is probably the simplest way to run and manage Uvicorn in a production setting. Uvicorn includes a gunicorn worker class that means you can get set up with very little configuration.

The following will start Gunicorn with four worker processes:

`gunicorn -w 4 -k uvicorn.workers.UvicornWorker`

The `UvicornWorker` implementation uses the `uvloop` and `httptools` implementations. To run under PyPy you'll want to use pure-python implementation instead. You can do this by using the `UvicornH11Worker` class.

`gunicorn -w 4 -k uvicorn.workers.UvicornH11Worker`

Gunicorn provides a different set of configuration options to Uvicorn, so  some options such as `--limit-concurrency` are not yet supported when running with Gunicorn.

### Supervisor

To use `supervisor` as a process manager you should either:

* Hand over the socket to uvicorn using its file descriptor, which supervisor always makes available as `0`, and which must be set in the `fcgi-program` section.
* Or use a UNIX domain socket for each `uvicorn` process.

A simple supervisor configuration might look something like this:

**supervisord.conf**:

```
[supervisord]

[fcgi-program:uvicorn]
socket=tcp://localhost:8000
command=venv/bin/uvicorn --fd 0 example:App
numprocs=4
process_name=uvicorn-%(process_num)d
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
```

Then run with `supervisord -n`.

### Circus

To use `circus` as a process manager, you should either:

* Hand over the socket to uvicorn using its file descriptor, which circus makes available as `$(circus.sockets.web)`.
* Or use a UNIX domain socket for each `uvicorn` process.

A simple circus configuration might look something like this:

**circus.ini**:

```
[watcher:web]
cmd = venv/bin/uvicorn --fd $(circus.sockets.web) example:App
use_sockets = True
numprocesses = 4

[socket:web]
host = 0.0.0.0
port = 8000
```

Then run `circusd circus.ini`.

## Running behind Nginx

Using Nginx as a proxy in front of your Uvicorn processes may not be neccessary, but is recommended for additional resiliance. Nginx can deal with serving your static media and buffering slow requests, leaving your application servers free from load as much as possible.

In managed environments such as `Heroku`, you wont typically need to configure Nginx, as your server processes will already be running behind load balancing proxies.

The recommended configuration for proxying from Nginx is to use a UNIX domain socket between Nginx and whatever the process manager that is being used to run Uvicorn.

When fronting the application with a proxy server you want to make sure that the proxy sets headers to ensure that application can properly determine the client address of the incoming connection, and if the connection was over `http` or `https`.

You should ensure that the `X-Forwarded-For` and `X-Forwarded-Proto` headers are set by the proxy, and that Uvicorn is run using the `--proxy-headers` setting. This ensure that the ASGI scope includes correct `client` and `scheme` information.

Here's how a simple Nginx configuration might look. This example includes setting proxy headers, and using a UNIX domain socket to communicate with the application server.

```
http {
  server {
    listen 80;
    client_max_body_size 4G;

    server_name example.com;

    location / {
      proxy_set_header Host $http_host;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header X-Forwarded-Proto $scheme;
      proxy_redirect off;
      proxy_buffering off;
      proxy_pass http://uvicorn;
    }

    location /static {
      # path for static files
      root /path/to/app/static;
    }
  }

  upstream uvicorn {
    server unix:/tmp/uvicorn.sock;
  }

}
```

Uvicorn's `--proxy-headers` behavior may not be sufficient for more complex proxy configurations that use different combinations of headers, or where the application is running behind more than one intermediary proxying service.

In those cases you might want to use an ASGI middleware to set the `client` and `scheme` dependant on the request headers.

## Running behind a CDN

Running behind a content delivery network, such as Cloudflare or Cloud Front, provides a serious layer of protection against DDOS attacks. Your sevice will be running behind huge clusters of proxies and load balancers that are designed for handling huge amounts of traffic, and have capabilities for detecting and closing off connections from DDOS attacks.

Proper usage of cache control headers can mean that a CDN is able to serve large amounts of data without always having to forward the request on to your server.

Content Delivery Networks can also be a low-effort way to provide HTTPS termination.
