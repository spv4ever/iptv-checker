from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from iptv_checker.xtream import (
    XtreamAccount,
    XtreamClient,
    XtreamDatabase,
    expiration_from_api,
    parse_xtream_url,
)


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def read(self) -> bytes:
        return self.body


class XtreamUrlTest(unittest.TestCase):
    def test_parses_get_url_without_leaking_credentials_in_access_url(self) -> None:
        account = parse_xtream_url(
            "HTTPS://Demo.Example:8080/get.php?username=alice&password=s3cret&type=m3u_plus"
        )

        self.assertEqual(account.server_name, "demo.example:8080")
        self.assertEqual(account.access_url, "https://demo.example:8080")
        self.assertEqual(account.username, "alice")
        self.assertEqual(account.password, "s3cret")

    def test_parses_direct_stream_url(self) -> None:
        account = parse_xtream_url("http://tv.example/live/bob/key/123.ts")
        self.assertEqual((account.username, account.password), ("bob", "key"))

    def test_rejects_url_without_credentials(self) -> None:
        with self.assertRaises(ValueError):
            parse_xtream_url("https://example.com/get.php")

    def test_converts_api_expiration(self) -> None:
        self.assertEqual(
            expiration_from_api("1893456000"),
            datetime(2030, 1, 1, tzinfo=timezone.utc),
        )
        self.assertIsNone(expiration_from_api(None))


class XtreamDatabaseTest(unittest.TestCase):
    def test_saves_and_updates_segmented_account(self) -> None:
        with TemporaryDirectory() as directory:
            database = XtreamDatabase(Path(directory) / "data" / "xtream.db")
            first = XtreamAccount("Servidor", "https://example.com", "user", "old")
            valid_until = datetime(2030, 1, 1, tzinfo=timezone.utc)
            updated = XtreamAccount(
                "Servidor principal",
                "https://example.com",
                "user",
                "new",
                True,
                datetime(2026, 9, 12, tzinfo=timezone.utc),
                valid_until,
            )

            self.assertEqual(database.save(first), database.save(updated))
            self.assertEqual(database.all(), (updated,))

    def test_rejects_naive_validation_date(self) -> None:
        with TemporaryDirectory() as directory:
            database = XtreamDatabase(Path(directory) / "xtream.db")
            account = XtreamAccount(
                "Servidor", "https://example.com", "user", "pass", validated_at=datetime.now()
            )
            with self.assertRaises(ValueError):
                database.save(account)


class XtreamClientTest(unittest.TestCase):
    @patch("iptv_checker.xtream.urlopen")
    def test_gets_account_details_and_live_channels(self, urlopen_mock) -> None:
        urlopen_mock.side_effect = [
            FakeResponse(
                b'{"user_info":{"status":"Active","exp_date":"1893456000",'
                b'"active_cons":"1","max_connections":"2"}}'
            ),
            FakeResponse(b'[{"category_id":"7","category_name":"Noticias"}]'),
            FakeResponse(
                b'[{"stream_id":"42","name":"Canal Uno","category_id":"7",'
                b'"container_extension":"m3u8"}]'
            ),
        ]
        account = XtreamAccount(
            "Servidor", "https://tv.example:8080", "alice", "secret word"
        )

        details = XtreamClient(account, timeout=3).details()

        self.assertEqual(details.status, "Active")
        self.assertEqual((details.active_connections, details.max_connections), (1, 2))
        self.assertEqual(details.valid_until, datetime(2030, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(len(details.channels), 1)
        channel = details.channels[0]
        self.assertEqual((channel.stream_id, channel.name), (42, "Canal Uno"))
        self.assertEqual(channel.category_name, "Noticias")
        self.assertEqual(
            channel.direct_url,
            "https://tv.example:8080/live/alice/secret%20word/42.m3u8",
        )
        requested_url = urlopen_mock.call_args_list[2].args[0].full_url
        self.assertIn("action=get_live_streams", requested_url)
        self.assertIn("password=secret+word", requested_url)

    @patch("iptv_checker.xtream.urlopen")
    def test_uses_fallbacks_for_incomplete_channel_metadata(self, urlopen_mock) -> None:
        urlopen_mock.side_effect = [
            FakeResponse(b'{"user_info":{"status":"Active"}}'),
            FakeResponse(b"[]"),
            FakeResponse(b'[{"stream_id":9}]'),
        ]

        details = XtreamClient(
            XtreamAccount("Servidor", "http://tv.example", "u", "p")
        ).details()

        self.assertEqual(details.channels[0].name, "Canal 9")
        self.assertEqual(details.channels[0].category_name, "Sin categor\u00eda")
        self.assertEqual(details.channels[0].container_extension, "ts")


if __name__ == "__main__":
    unittest.main()
