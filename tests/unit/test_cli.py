"""Configuração de porta do processo HTTP em plataformas gerenciadas."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from services.api.cli import build_parser


class CliConfigurationTests(unittest.TestCase):
    def test_platform_port_is_used_when_aurafi_override_is_absent(self) -> None:
        with patch.dict(os.environ, {"PORT": "10000"}, clear=True):
            self.assertEqual(build_parser().parse_args([]).port, 10000)

    def test_aurafi_port_has_precedence(self) -> None:
        with patch.dict(
            os.environ,
            {"PORT": "10000", "AURAFI_API_PORT": "9000"},
            clear=True,
        ):
            self.assertEqual(build_parser().parse_args([]).port, 9000)


if __name__ == "__main__":
    unittest.main()
