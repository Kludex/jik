import json
import socket
from copy import deepcopy

import pytest
import yaml

from uvicorn import protocols
from uvicorn.config import LOGGING_CONFIG, Config
from uvicorn.middleware.debug import DebugMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from uvicorn.middleware.wsgi import WSGIMiddleware


@pytest.fixture
def mocked_logging_config_module(mocker):
    return mocker.patch("logging.config")


@pytest.fixture
def logging_config():
    return deepcopy(LOGGING_CONFIG)


@pytest.fixture
def json_logging_config(logging_config):
    return json.dumps(logging_config)


@pytest.fixture
def yaml_logging_config(logging_config):
    return yaml.dump(logging_config)


async def asgi_app():
    pass  # pragma: nocover


def wsgi_app():
    pass  # pragma: nocover


def test_debug_app():
    config = Config(app=asgi_app, debug=True, proxy_headers=False)
    config.load()

    assert config.debug is True
    assert isinstance(config.loaded_app, DebugMiddleware)


def test_wsgi_app():
    config = Config(app=wsgi_app, interface="wsgi", proxy_headers=False)
    config.load()

    assert isinstance(config.loaded_app, WSGIMiddleware)
    assert config.interface == "wsgi"
    assert config.asgi_version == "3.0"


def test_proxy_headers():
    config = Config(app=asgi_app)
    config.load()

    assert config.proxy_headers is True
    assert isinstance(config.loaded_app, ProxyHeadersMiddleware)


def test_app_unimportable():
    config = Config(app="no.such:app")
    with pytest.raises(ImportError):
        config.load()


def test_concrete_http_class():
    config = Config(app=asgi_app, http=protocols.http.h11_impl.H11Protocol)
    config.load()
    assert config.http_protocol_class is protocols.http.h11_impl.H11Protocol


def test_socket_bind():
    config = Config(app=asgi_app)
    config.load()

    assert isinstance(config.bind_socket(), socket.socket)


def test_ssl_config(certfile_and_keyfile):
    certfile, keyfile = certfile_and_keyfile
    config = Config(app=asgi_app, ssl_certfile=certfile, ssl_keyfile=keyfile)
    config.load()

    assert config.is_ssl is True


def asgi2_app(scope):
    async def asgi(receive, send):
        pass

    return asgi


@pytest.mark.parametrize(
    "app, expected_interface", [(asgi_app, "3.0"), (asgi2_app, "2.0")]
)
def test_asgi_version(app, expected_interface):
    config = Config(app=app)
    config.load()
    assert config.asgi_version == expected_interface


@pytest.mark.parametrize(
    "use_colors, expected",
    [
        pytest.param(None, None, id="use_colors_not_provided"),
        pytest.param(True, True, id="use_colors_enabled"),
        pytest.param(False, False, id="use_colors_disabled"),
        pytest.param("invalid", False, id="use_colors_invalid_value"),
    ],
)
def test_log_config_default(mocked_logging_config_module, use_colors, expected):
    """
    Test that one can specify the use_colors option when using the default logging
    config.
    """
    config = Config(app=asgi_app, use_colors=use_colors)
    config.load()

    mocked_logging_config_module.dictConfig.assert_called_once_with(LOGGING_CONFIG)

    (provided_dict_config,), _ = mocked_logging_config_module.dictConfig.call_args
    assert provided_dict_config["formatters"]["default"]["use_colors"] == expected


def test_log_config_json(
    mocked_logging_config_module, logging_config, json_logging_config, mocker
):
    """
    Test that one can load a json config from disk.
    """
    mocked_open = mocker.patch(
        "uvicorn.config.open", mocker.mock_open(read_data=json_logging_config)
    )

    config = Config(app=asgi_app, log_config="log_config.json")
    config.load()

    mocked_open.assert_called_once_with("log_config.json")
    mocked_logging_config_module.dictConfig.assert_called_once_with(logging_config)


@pytest.mark.parametrize("config_filename", ["log_config.yml", "log_config.yaml"])
def test_log_config_yaml(
    mocked_logging_config_module,
    logging_config,
    yaml_logging_config,
    mocker,
    config_filename,
):
    """
    Test that one can load a yaml config from disk.
    """
    mocked_open = mocker.patch(
        "uvicorn.config.open", mocker.mock_open(read_data=yaml_logging_config)
    )

    config = Config(app=asgi_app, log_config=config_filename)
    config.load()

    mocked_open.assert_called_once_with(config_filename)
    mocked_logging_config_module.dictConfig.assert_called_once_with(logging_config)


def test_log_config_file(mocked_logging_config_module):
    """
    Test that one can load a configparser config from disk.
    """
    config = Config(app=asgi_app, log_config="log_config")
    config.load()

    mocked_logging_config_module.fileConfig.assert_called_once_with(
        "log_config", disable_existing_loggers=False
    )
