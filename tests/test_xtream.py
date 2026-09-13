from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from iptv_checker.xtream import (
    XtreamAccount,
    XtreamClient,
    XtreamDatabase,
    account_guid,
    expiration_from_api,
    parse_xtream_url,
    xtream_playlist_url,
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

    def test_builds_stable_identity_and_reconstructs_check_url(self) -> None:
        account = parse_xtream_url(
            "https://TV.example/get.php?password=secret+word&username=alice"
        )

        self.assertEqual(
            account_guid(account.access_url, account.username, account.password),
            account_guid("https://tv.example/", "alice", "secret word"),
        )
        self.assertEqual(
            xtream_playlist_url(account),
            "https://tv.example/get.php?username=alice&password=secret+word&type=m3u_plus",
        )


class XtreamDatabaseTest(unittest.TestCase):
    def test_pending_import_is_idempotent_and_does_not_reset_validation(self) -> None:
        with TemporaryDirectory() as directory:
            database = XtreamDatabase(Path(directory) / "xtream.db")
            account = XtreamAccount("Servidor", "https://example.com", "user", "pass")

            identifier, created = database.save_pending(account)
            same_identifier, duplicated = database.save_pending(account)
            database.save(
                XtreamAccount("Servidor", "https://example.com", "user", "pass", True)
            )
            _identifier, duplicated_after_validation = database.save_pending(account)

            self.assertTrue(created)
            self.assertFalse(duplicated)
            self.assertFalse(duplicated_after_validation)
            self.assertEqual(identifier, same_identifier)
            self.assertTrue(database.all()[0].is_valid)

    def test_selects_a_configurable_global_batch_in_insertion_order(self) -> None:
        with TemporaryDirectory() as directory:
            database = XtreamDatabase(Path(directory) / "xtream.db")
            for server in ("https://one", "https://two"):
                for index in range(7):
                    database.save_pending(
                        XtreamAccount(server, server, f"user-{index}", "pass")
                    )
            database.save(XtreamAccount("Uno", "https://one", "user-0", "pass", True))

            pending = database.pending_batches(8)

            self.assertEqual(len(pending), 8)
            self.assertEqual(
                [(account.access_url, account.username) for account in pending],
                [
                    *(("https://one", f"user-{index}") for index in range(1, 7)),
                    ("https://two", "user-0"),
                    ("https://two", "user-1"),
                ],
            )

    def test_rejects_invalid_pending_batch_size(self) -> None:
        with TemporaryDirectory() as directory:
            database = XtreamDatabase(Path(directory) / "xtream.db")

            with self.assertRaises(ValueError):
                database.pending_batches(0)

    def test_keeps_changed_credentials_as_a_distinct_account(self) -> None:
        with TemporaryDirectory() as directory:
            database = XtreamDatabase(Path(directory) / "xtream.db")

            database.save_pending(XtreamAccount("Servidor", "https://one", "user", "old"))
            _identifier, created = database.save_pending(
                XtreamAccount("Servidor", "https://one", "user", "new")
            )

            self.assertTrue(created)
            self.assertEqual(len(database.all()), 2)

    def test_saves_and_updates_the_same_segmented_account(self) -> None:
        with TemporaryDirectory() as directory:
            database = XtreamDatabase(Path(directory) / "data" / "xtream.db")
            first = XtreamAccount("Servidor", "https://example.com", "user", "old")
            valid_until = datetime(2030, 1, 1, tzinfo=timezone.utc)
            updated = XtreamAccount(
                "Servidor principal",
                "https://example.com",
                "user",
                "old",
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

    def test_deletes_failed_and_expired_accounts_only(self) -> None:
        with TemporaryDirectory() as directory:
            database = XtreamDatabase(Path(directory) / "xtream.db")
            now = datetime(2026, 9, 12, tzinfo=timezone.utc)
            database.save(
                XtreamAccount(
                    "Activa",
                    "https://active",
                    "u",
                    "p",
                    True,
                    valid_until=datetime(2030, 1, 1, tzinfo=timezone.utc),
                )
            )
            database.save(XtreamAccount("Fallida", "https://failed", "u", "p", False))
            database.save(
                XtreamAccount(
                    "Caducada",
                    "https://expired",
                    "u",
                    "p",
                    True,
                    valid_until=datetime(2020, 1, 1, tzinfo=timezone.utc),
                )
            )

            self.assertEqual(database.delete_obsolete("Fallida", now=now), 1)
            self.assertEqual(database.delete_obsolete("Caducada", now=now), 1)
            self.assertEqual([account.server_name for account in database.all()], ["Activa"])

    def test_deletes_only_accounts_from_selected_server(self) -> None:
        with TemporaryDirectory() as directory:
            database = XtreamDatabase(Path(directory) / "xtream.db")
            database.save(XtreamAccount("Uno", "https://one", "u", "p"))
            database.save(XtreamAccount("Uno", "https://one-2", "u2", "p"))
            database.save(XtreamAccount("Dos", "https://two", "u", "p"))

            self.assertEqual(database.delete_server("Uno"), 2)
            self.assertEqual(
                [account.server_name for account in database.all()], ["Dos"]
            )
            self.assertEqual(database.delete_server("Uno"), 0)

    def test_obsolete_cleanup_does_not_touch_other_servers(self) -> None:
        with TemporaryDirectory() as directory:
            database = XtreamDatabase(Path(directory) / "xtream.db")
            database.save(XtreamAccount("Uno", "https://one", "u", "p", False))
            database.save(XtreamAccount("Dos", "https://two", "u", "p", False))

            self.assertEqual(database.delete_obsolete("Uno"), 1)
            self.assertEqual(
                [account.server_name for account in database.all()], ["Dos"]
            )


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
