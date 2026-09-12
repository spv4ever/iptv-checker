from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from iptv_checker.xtream import (
    XtreamAccount,
    XtreamDatabase,
    expiration_from_api,
    parse_xtream_url,
)


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


if __name__ == "__main__":
    unittest.main()
