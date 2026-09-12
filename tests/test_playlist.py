import unittest

from iptv_checker.playlist import normalize_url, parse_m3u, parse_urls


class ParseM3UTest(unittest.TestCase):
    def test_removes_vlc_quotes_and_markdown_wrappers(self) -> None:
        url = "http://tv.example/live/user/password/1064.ts"

        self.assertEqual(normalize_url(f"«{url}»"), url)
        self.assertEqual(normalize_url(f"[{url}»]({url}»)"), url)

    def test_reads_metadata_and_urls(self) -> None:
        parsed = parse_m3u(
            '#EXTM3U\n#EXTINF:-1 tvg-id="news" group-title="Info",Noticias\n'
            "https://example.com/live.m3u8\n"
        )

        self.assertEqual(len(parsed.channels), 1)
        self.assertEqual(parsed.channels[0].name, "Noticias")
        self.assertEqual(parsed.channels[0].attributes["tvg-id"], "news")
        self.assertEqual(parsed.warnings, ())

    def test_reports_unsupported_and_incomplete_entries(self) -> None:
        parsed = parse_m3u("#EXTINF:-1,Radio\nudp://example.com\n#EXTINF:-1,Sin URL\n")

        self.assertEqual(parsed.channels, ())
        self.assertEqual(len(parsed.warnings), 2)

    def test_reads_plain_url_list_and_reports_invalid_lines(self) -> None:
        parsed = parse_urls("https://example.com/live\nno-es-url\n\nhttp://example.org\n")

        self.assertEqual(
            [channel.url for channel in parsed.channels],
            ["https://example.com/live", "http://example.org"],
        )
        self.assertEqual(len(parsed.warnings), 1)
        self.assertIn("Línea 2", parsed.warnings[0])


if __name__ == "__main__":
    unittest.main()
