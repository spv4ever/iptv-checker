from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from iptv_checker.checker import CheckResult
from iptv_checker.gui import (
    _account_row,
    _apply_live_check,
    _check_live_channels,
    _channel_matches_filters,
    _embedded_player_command,
    _live_worker_count,
    _open_stream,
    _player_command,
    _save_available_account,
)
from iptv_checker.playlist import Channel
from iptv_checker.xtream import XtreamAccount, XtreamChannel, XtreamDatabase, XtreamDetails


class SavedAccountsViewTest(unittest.TestCase):
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

    @patch("iptv_checker.gui.shutil.which", return_value="/opt/mpv")
    def test_builds_embedded_mpv_command_with_volume(self, _which_mock) -> None:
        command, environment = _embedded_player_command("mpv", 12345, 72)

        self.assertEqual(command[0], "/opt/mpv")
        self.assertIn("--wid=12345", command)
        self.assertIn("--volume=72", command)
        self.assertNotIn("SDL_WINDOWID", environment)

    @patch("iptv_checker.gui.shutil.which", return_value="/opt/ffplay")
    def test_builds_embedded_ffplay_environment(self, _which_mock) -> None:
        command, environment = _embedded_player_command("ffplay", 987, 65)

        self.assertEqual(command[-2:], ["-volume", "65"])
        self.assertEqual(environment["SDL_WINDOWID"], "987")

    @patch("iptv_checker.gui.shutil.which", return_value=None)
    def test_embedded_player_must_still_be_installed(self, _which_mock) -> None:
        with self.assertRaisesRegex(OSError, "ya no está disponible"):
            _embedded_player_command("mpv", 1, 80)

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
