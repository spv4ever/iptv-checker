from datetime import datetime, timezone
import unittest

from iptv_checker.gui import _account_row
from iptv_checker.xtream import XtreamAccount


class SavedAccountsViewTest(unittest.TestCase):
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
        self.assertEqual(row[-1], "—")

    def test_formats_unknown_validation_status(self) -> None:
        account = XtreamAccount("Servidor", "https://example.com", "bob", "clave")

        self.assertEqual(_account_row(account)[3], "Sin validar")
