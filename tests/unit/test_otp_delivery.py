from __future__ import annotations

import smtplib
import unittest
from email.message import EmailMessage

from services.identity.otp_delivery import (
    OtpDeliveryConfigurationError,
    OtpDeliveryTransportError,
    SmtpOtpDelivery,
    SmtpOtpDeliveryConfig,
)
from services.identity.service import ChannelContext, OtpDeliveryMessage


def make_message(otp: str = "834201") -> OtpDeliveryMessage:
    return OtpDeliveryMessage(
        challenge_id="chl_123",
        email="maria@example.com",
        otp=otp,
        channel=ChannelContext.from_value("web_widget"),
        correlation_id="cor_123",
    )


class FakeSmtp:
    instances: list["FakeSmtp"] = []

    def __init__(self, host: str, port: int, *, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.logged_in: tuple[str, str] | None = None
        self.message: EmailMessage | None = None
        self.__class__.instances.append(self)

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def starttls(self, *, context) -> None:
        self.started_tls = True

    def login(self, user: str, password: str) -> None:
        self.logged_in = (user, password)

    def send_message(self, message: EmailMessage) -> None:
        self.message = message


class FailingSmtp(FakeSmtp):
    def send_message(self, message: EmailMessage) -> None:
        raise smtplib.SMTPException("server rejected message")


class OtpDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeSmtp.instances.clear()

    def test_delivers_message_through_injected_fake_with_timeout_and_tls(self) -> None:
        config = SmtpOtpDeliveryConfig(
            host="smtp.example.test",
            port=587,
            from_email="no-reply@aurafi.example",
            username="mailer",
            password="secret-not-for-logs",
            timeout=3.5,
        )
        adapter = SmtpOtpDelivery(config, smtp_factory=FakeSmtp)

        adapter.deliver(make_message())

        smtp = FakeSmtp.instances[0]
        self.assertEqual((smtp.host, smtp.port, smtp.timeout), ("smtp.example.test", 587, 3.5))
        self.assertTrue(smtp.started_tls)
        self.assertEqual(smtp.logged_in, ("mailer", "secret-not-for-logs"))
        assert smtp.message is not None
        self.assertEqual(smtp.message["To"], "maria@example.com")
        self.assertIn("834201", smtp.message.get_content())

    def test_from_env_requires_explicit_host_and_sender(self) -> None:
        with self.assertRaises(OtpDeliveryConfigurationError):
            SmtpOtpDeliveryConfig.from_env({})

    def test_rejects_incomplete_credentials_and_insecure_transport(self) -> None:
        with self.assertRaises(OtpDeliveryConfigurationError):
            SmtpOtpDeliveryConfig(
                host="smtp.example.test",
                from_email="no-reply@aurafi.example",
                username="mailer",
            )
        with self.assertRaises(OtpDeliveryConfigurationError):
            SmtpOtpDeliveryConfig(
                host="smtp.example.test",
                from_email="no-reply@aurafi.example",
                starttls=False,
                ssl=False,
            )

    def test_timeout_must_be_positive(self) -> None:
        with self.assertRaises(OtpDeliveryConfigurationError):
            SmtpOtpDeliveryConfig(
                host="smtp.example.test",
                from_email="no-reply@aurafi.example",
                timeout=0,
            )

    def test_password_is_not_in_config_repr_or_transport_error(self) -> None:
        secret = "secret-not-for-logs"
        config = SmtpOtpDeliveryConfig(
            host="smtp.example.test",
            from_email="no-reply@aurafi.example",
            username="mailer",
            password=secret,
        )
        self.assertNotIn(secret, repr(config))

        adapter = SmtpOtpDelivery(config, smtp_factory=FailingSmtp)
        with self.assertRaises(OtpDeliveryTransportError) as raised:
            adapter.deliver(make_message())
        self.assertNotIn(secret, str(raised.exception))
        self.assertNotIn("834201", str(raised.exception))

    def test_invalid_otp_is_rejected_before_transport(self) -> None:
        adapter = SmtpOtpDelivery(
            SmtpOtpDeliveryConfig(
                host="smtp.example.test",
                from_email="no-reply@aurafi.example",
            ),
            smtp_factory=FakeSmtp,
        )

        with self.assertRaises(OtpDeliveryConfigurationError):
            adapter.deliver(make_message("123"))
        self.assertEqual(FakeSmtp.instances, [])


if __name__ == "__main__":
    unittest.main()
