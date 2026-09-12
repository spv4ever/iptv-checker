from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from iptv_checker.checker import CheckResult
from iptv_checker.gui import _account_row, _open_stream, _save_available_account
from iptv_checker.playlist import Channel
from iptv_checker.xtream import XtreamAccount, XtreamDatabase


class SavedAccountsViewTest(unittest.TestCase):
    @patch("iptv_checker.gui.webbrowser.open", return_value=True)
    def test_opens_channel_in_default_player(self, open_mock) -> None:
        url = "https://tv.example/live/alice/secret/42.ts"

        self.assertTrue(_open_stream(url))

        open_mock.assert_called_once_with(url, new=2)

    def test_formats_saved_account_without_exposing_password(self) -> None:
        account = XtreamAccount(
            "Servidor principal",
            "https://example.com",
            "alice",
            "secreto",
            True,
            datetime(2026, 9, 12, 14, 30, tzinfo=timezone.utc),
            None,
        )

        row = _account_row(account)

        self.assertEqual(
            row[:4],
            ("Servidor principal", "https://example.com", "alice", "Válida"),
        )
        self.assertNotIn("secreto", row)
        self.assertEqual(row[4], "—")
        self.assertEqual(row[-1], "—")

    def test_formats_unknown_validation_status(self) -> None:
        account = XtreamAccount("Servidor", "https://example.com", "bob", "clave")

        self.assertEqual(_account_row(account)[3], "Sin validar")

    def test_saves_available_xtream_url_after_checking_it(self) -> None:
        with TemporaryDirectory() as directory:
            database_path = Path(directory) / "xtream.db"
            result = CheckResult(
                Channel(
                    "Cuenta",
                    "https://tv.example:8080/get.php?username=alice&password=secret&type=m3u_plus",
                ),
                True,
                200,
                15,
            )

            self.assertTrue(_save_available_account(result, database_path))

            (saved,) = XtreamDatabase(database_path).all()
            self.assertEqual(saved.access_url, "https://tv.example:8080")
            self.assertEqual(saved.username, "alice")
            self.assertEqual(saved.password, "secret")
            self.assertTrue(saved.is_valid)
            self.assertIsNotNone(saved.validated_at)

    def test_does_not_save_url_when_check_fails(self) -> None:
        with TemporaryDirectory() as directory:
            database_path = Path(directory) / "xtream.db"
            result = CheckResult(
                Channel("Cuenta", "https://tv.example/get.php?username=a&password=b"),
                False,
                404,
                10,
                "HTTP 404",
            )

            self.assertFalse(_save_available_account(result, database_path))
            self.assertFalse(database_path.exists())
