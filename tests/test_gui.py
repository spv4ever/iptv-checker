from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from iptv_checker.checker import CheckResult
from iptv_checker.gui import (
    ALL_SERVERS,
    _account_is_obsolete,
    _account_row,
    _apply_live_check,
    _check_live_channels,
    _channel_matches_filters,
    _filter_accounts_by_server,
    _filter_live_rows,
    _details_are_valid,
    _live_worker_count,
    _open_stream,
    _player_command,
    _save_available_account,
    _server_filter_values,
    _set_live_filters_enabled,
)
from iptv_checker.playlist import Channel
from iptv_checker.xtream import XtreamAccount, XtreamChannel, XtreamDatabase, XtreamDetails


class SavedAccountsViewTest(unittest.TestCase):
    def test_lists_unique_server_names_for_saved_accounts_filter(self) -> None:
        accounts = (
            XtreamAccount("Zulu", "https://z.example", "one", "secret"),
            XtreamAccount("alpha", "https://a.example", "two", "secret"),
            XtreamAccount("Zulu", "https://z.example", "three", "secret"),
        )

        self.assertEqual(
            _server_filter_values(accounts),
            (ALL_SERVERS, "alpha", "Zulu"),
        )

    def test_filters_saved_accounts_by_exact_server_name(self) -> None:
        accounts = (
            XtreamAccount("Servidor A", "https://a.example", "one", "secret"),
            XtreamAccount("Servidor B", "https://b.example", "two", "secret"),
            XtreamAccount("Servidor A", "https://a.example", "three", "secret"),
        )

        filtered = _filter_accounts_by_server(accounts, "Servidor A")

        self.assertEqual([account.username for account in filtered], ["one", "three"])
        self.assertIs(_filter_accounts_by_server(accounts, ALL_SERVERS), accounts)

    def test_reenables_category_filter_after_live_check_finishes(self) -> None:
        channel_entry = Mock()
        category_box = Mock()

        _set_live_filters_enabled(channel_entry, category_box, enabled=True)

        channel_entry.state.assert_called_once_with(["!disabled"])
        category_box.state.assert_called_once_with(["!disabled", "readonly"])

    def test_disables_live_filters_while_check_is_running(self) -> None:
        channel_entry = Mock()
        category_box = Mock()

        _set_live_filters_enabled(channel_entry, category_box, enabled=False)

        channel_entry.state.assert_called_once_with(["disabled"])
        category_box.state.assert_called_once_with(["disabled"])

    def test_selects_only_live_rows_matching_both_filters(self) -> None:
        rows = [
            ("row-1", (1, "Noticias 24", "España", "ts", "Pendiente", "http://one")),
            ("row-2", (2, "Cine Plus", "España", "ts", "Pendiente", "http://two")),
            ("row-3", (3, "Noticias MX", "México", "ts", "Pendiente", "http://three")),
        ]

        selected = _filter_live_rows(rows, "noticias", "España")

        self.assertEqual([item for item, _values in selected], ["row-1"])

    def test_filters_channels_by_free_text_and_category(self) -> None:
        self.assertTrue(
            _channel_matches_filters("Canal Noticias HD", "España", "noticias", "Todas")
        )
        self.assertTrue(
            _channel_matches_filters("Canal Noticias HD", "España", "CANAL", "España")
        )
        self.assertFalse(
            _channel_matches_filters("Canal Noticias HD", "España", "cine", "Todas")
        )
        self.assertFalse(
            _channel_matches_filters("Canal Noticias HD", "España", "canal", "México")
        )

    def test_removes_unavailable_channels_from_the_live_table(self) -> None:
        table = Mock()
        result = CheckResult(Channel("Caído", "http://tv.example/1"), False, 404, 5)

        _apply_live_check(table, "row-1", result)

        table.delete.assert_called_once_with("row-1")
        table.set.assert_not_called()

    def test_keeps_and_marks_available_channels_in_the_live_table(self) -> None:
        table = Mock()
        result = CheckResult(Channel("Activo", "http://tv.example/2"), True, 200, 5)

        _apply_live_check(table, "row-2", result)

        table.set.assert_called_once_with("row-2", "availability", "Accesible")
        table.item.assert_called_once_with("row-2", tags=("ok",))
        table.delete.assert_not_called()

    def test_scales_live_checks_up_to_the_worker_limit(self) -> None:
        self.assertEqual(_live_worker_count(0), 1)
        self.assertEqual(_live_worker_count(7), 7)
        self.assertEqual(_live_worker_count(500), 20)

    @patch("iptv_checker.gui.PlaylistChecker.check_all")
    def test_checks_every_live_stream_before_it_can_be_opened(self, check_all_mock) -> None:
        channels = (
            XtreamChannel(1, "Disponible", "", "", "ts", "http://tv.example/live/u/p/1.ts"),
            XtreamChannel(2, "Caído", "", "", "ts", "http://tv.example/live/u/p/2.ts"),
        )
        details = XtreamDetails("Active", None, 0, 1, channels)
        check_all_mock.return_value = [
            CheckResult(
                Channel(channel.name, channel.direct_url),
                index == 0,
                200 if index == 0 else 404,
                5,
            )
            for index, channel in enumerate(channels)
        ]

        results = _check_live_channels(details, timeout=3)

        checked = check_all_mock.call_args.args[0]
        self.assertEqual(
            [channel.url for channel in checked],
            [channel.direct_url for channel in channels],
        )
        self.assertEqual([result.available for result in results], [True, False])

    @patch("iptv_checker.gui.subprocess.Popen")
    @patch("iptv_checker.gui._player_command", return_value=("mpv", ["/usr/bin/mpv"]))
    def test_opens_authenticated_channel_in_player(self, _player_mock, popen_mock) -> None:
        url = "https://tv.example/live/alice/secret/42.ts"

        self.assertEqual(_open_stream(url), "mpv")

        popen_mock.assert_called_once()
        self.assertEqual(popen_mock.call_args.args[0], ["/usr/bin/mpv", url])

    @patch("iptv_checker.gui.subprocess.Popen")
    @patch("iptv_checker.gui._player_command", return_value=("VLC", ["/usr/bin/vlc"]))
    def test_removes_copied_message_wrappers_before_opening_vlc(
        self, _vlc_mock, popen_mock
    ) -> None:
        url = "http://tv.example/live/user/password/1064.ts"

        self.assertTrue(_open_stream(f"«{url}»"))

        self.assertEqual(popen_mock.call_args.args[0], ["/usr/bin/vlc", url])

    @patch("iptv_checker.gui._player_command", return_value=None)
    def test_reports_when_no_player_is_installed(self, _player_mock) -> None:
        self.assertFalse(_open_stream("https://tv.example/live/u/p/42.ts"))

    @patch("iptv_checker.gui._vlc_executable", return_value="/opt/vlc")
    @patch("iptv_checker.gui.shutil.which")
    def test_prefers_mpv_and_falls_back_to_vlc(self, which_mock, _vlc_mock) -> None:
        which_mock.side_effect = lambda name: "/opt/mpv" if name == "mpv" else None
        self.assertEqual(_player_command(), ("mpv", ["/opt/mpv", "--force-window=yes"]))

        which_mock.side_effect = lambda _name: None
        self.assertEqual(_player_command(), ("VLC", ["/opt/vlc"]))

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

        self.assertEqual(_account_row(account)[3], "Pendiente sin validar")

    def test_marks_expired_account_as_obsolete(self) -> None:
        account = XtreamAccount(
            "Servidor", "https://example.com", "bob", "clave", True,
            valid_until=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )

        self.assertTrue(_account_is_obsolete(account))
        self.assertEqual(_account_row(account)[3], "Obsoleta")

    def test_rejects_active_details_when_expiration_has_passed(self) -> None:
        details = XtreamDetails(
            "Active", datetime(2020, 1, 1, tzinfo=timezone.utc), 0, 1, ()
        )

        self.assertFalse(_details_are_valid(details))

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
