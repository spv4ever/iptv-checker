import unittest

from iptv_checker.playlist import parse_m3u


class ParseM3UTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
