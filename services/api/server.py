"""Transporte HTTP stdlib para a aplicacao local do AuraFi."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any, Callable

from .app import AuraFiApp, MAX_BODY_BYTES, Request, Response, create_app


class _AuraFiHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class AuraFiRequestHandler(BaseHTTPRequestHandler):
    """Adapter fino entre ``BaseHTTPRequestHandler`` e ``AuraFiApp``."""

    server_version = "AuraFiStdlib/1.0"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - nome definido pelo stdlib
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802 - nome definido pelo stdlib
        self._dispatch("POST")

    def do_PUT(self) -> None:  # noqa: N802 - nome definido pelo stdlib
        self._dispatch("PUT")

    def do_OPTIONS(self) -> None:  # noqa: N802 - nome definido pelo stdlib
        self._dispatch("OPTIONS")

    def _dispatch(self, method: str) -> None:
        request_headers = {key: value for key, value in self.headers.items()}
        try:
            body = self._read_body()
            request = Request(
                method=method,
                target=self.path,
                headers=request_headers,
                body=body,
            )
            response = self._app.handle(request)
        except RequestBodyError as exc:
            response = self._app._error_response(  # local transport error, same envelope
                Request(method, self.path, request_headers, None),
                exc.status,
                exc.code,
                str(exc),
                retryable=False,
            )
        except Exception:
            response = self._app._error_response(
                Request(method, self.path, request_headers, None),
                500,
                "INTERNAL_ERROR",
                "Nao foi possivel processar a requisicao.",
                retryable=True,
            )
        self._write_response(response)

    def _read_body(self) -> Any:
        raw_length = self.headers.get("Content-Length")
        if not raw_length:
            return None
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise RequestBodyError("Content-Length invalido.", code="INVALID_CONTENT_LENGTH") from exc
        if length < 0 or length > MAX_BODY_BYTES:
            raise RequestBodyError("Corpo da requisicao excede o limite permitido.", code="REQUEST_BODY_TOO_LARGE", status=413)
        raw = self.rfile.read(length)
        if not raw:
            return None
        try:
            decoded = raw.decode("utf-8")
            return json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RequestBodyError("O corpo deve ser JSON valido.", code="INVALID_JSON") from exc

    def _write_response(self, response: Response) -> None:
        status = int(response.status)
        payload = response.payload
        if status == 204 or payload is None:
            encoded = b""
        else:
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Request-ID, X-Correlation-ID, X-Channel")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        if isinstance(payload, dict):
            meta = payload.get("meta")
            if isinstance(meta, dict):
                request_id = meta.get("request_id")
                correlation_id = meta.get("correlation_id")
                if request_id:
                    self.send_header("X-Request-ID", str(request_id))
                if correlation_id:
                    self.send_header("X-Correlation-ID", str(correlation_id))
        for key, value in (response.headers or {}).items():
            self.send_header(str(key), str(value))
        self.end_headers()
        if encoded:
            self.wfile.write(encoded)

    def log_message(self, format: str, *args: Any) -> None:
        # Nao registrar headers ou corpo: evita vazamento acidental de token/OTP.
        super().log_message("%s", format % args)

    @property
    def _app(self) -> AuraFiApp:
        return self.server.aurafi_app  # type: ignore[attr-defined]


class RequestBodyError(ValueError):
    def __init__(self, message: str, *, code: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class AuraFiServer:
    """Servidor controlavel em testes e em execucao local."""

    def __init__(
        self,
        app: AuraFiApp | None = None,
        *,
        host: str = "127.0.0.1",
        port: int = 8000,
    ) -> None:
        self.app = app or create_app()
        self.httpd = _AuraFiHTTPServer((host, int(port)), AuraFiRequestHandler)
        self.httpd.aurafi_app = self.app  # type: ignore[attr-defined]
        self._thread: Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        host, port = self.httpd.server_address[:2]
        return str(host), int(port)

    @property
    def base_url(self) -> str:
        host, port = self.address
        display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
        return f"http://{display_host}:{port}"

    def serve_forever(self) -> None:
        try:
            self.httpd.serve_forever(poll_interval=0.05)
        finally:
            self.httpd.server_close()

    def start_background(self, *, name: str = "aurafi-api") -> Thread:
        if self._thread is not None and self._thread.is_alive():
            return self._thread
        self._thread = Thread(target=self.serve_forever, name=name, daemon=True)
        self._thread.start()
        return self._thread

    def shutdown(self, *, join_timeout: float = 2.0) -> None:
        self.httpd.shutdown()
        if self._thread is not None:
            self._thread.join(join_timeout)
        self.httpd.server_close()

    close = shutdown


def create_server(
    app: AuraFiApp | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> AuraFiServer:
    return AuraFiServer(app, host=host, port=port)


def run(
    *,
    app: AuraFiApp | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    """Entra no loop bloqueante ate SIGINT/SIGTERM do processo."""

    create_server(app, host=host, port=port).serve_forever()


__all__ = [
    "AuraFiRequestHandler",
    "AuraFiServer",
    "RequestBodyError",
    "create_server",
    "run",
]
