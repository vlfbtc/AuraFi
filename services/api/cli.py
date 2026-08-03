"""CLI de desenvolvimento para o servidor AuraFi."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:  # permite `python services/api/cli.py` em Python embutido
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from services.api.app import API_VERSION, DEFAULT_HOST, DEFAULT_PORT, create_app
    from services.api.server import create_server
else:
    from .app import API_VERSION, DEFAULT_HOST, DEFAULT_PORT, create_app
    from .server import create_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Servidor API do AuraFi")
    parser.add_argument("--host", default=os.environ.get("AURAFI_API_HOST", DEFAULT_HOST))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("AURAFI_API_PORT") or os.environ.get("PORT") or str(DEFAULT_PORT)),
        help="Porta TCP; use 0 para uma porta efemera em testes.",
    )
    parser.add_argument("--version", action="version", version=API_VERSION)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    server = create_server(create_app(), host=args.host, port=args.port)
    print(f"AuraFi API ouvindo em {server.base_url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":  # pragma: no cover - entrada de processo
    raise SystemExit(main())
