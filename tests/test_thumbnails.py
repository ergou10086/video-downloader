import unittest

from video_downloader.core.thumbnails import classify_thumbnail_result, thumbnail_written_path


class ThumbnailResultTests(unittest.TestCase):
    def test_converted_path_wins_over_source_path(self):
        # --convert-thumbnails 结束后原文件会被删除，报告给用户的必须是转换结果。
        output = (
            "[info] Downloading video thumbnail 45 ...\n"
            "[info] Writing video thumbnail 45 to: cover\\video.webp\n"
            '[ThumbnailsConvertor] Converting thumbnail "cover\\video.webp" to jpg\n'
        )
        self.assertEqual(thumbnail_written_path(output), "cover\\video.jpg")
        self.assertEqual(classify_thumbnail_result(0, output), "success")

    def test_written_path_without_conversion_is_used_as_is(self):
        output = "[info] Writing video thumbnail 45 to: cover\\video.jpg\n"
        self.assertEqual(thumbnail_written_path(output), "cover\\video.jpg")

    def test_already_downloaded_thumbnail_counts_as_success(self):
        output = "[download] cover\\video.jpg has already been downloaded\n"
        self.assertEqual(thumbnail_written_path(output), "cover\\video.jpg")
        self.assertEqual(classify_thumbnail_result(0, output), "success")

    def test_video_extension_does_not_masquerade_as_thumbnail(self):
        output = "[download] cover\\video.mp4 has already been downloaded\n"
        self.assertEqual(thumbnail_written_path(output), "")

    def test_missing_thumbnail_is_reported_as_missing(self):
        output = "[youtube] abc: Downloading webpage\n"
        self.assertEqual(thumbnail_written_path(output), "")
        self.assertEqual(classify_thumbnail_result(0, output), "missing")

    def test_nonzero_exit_is_an_error_even_with_thumbnail_output(self):
        output = "[info] Writing video thumbnail 45 to: cover\\video.jpg\n"
        self.assertEqual(classify_thumbnail_result(1, output), "error")


if __name__ == "__main__":
    unittest.main()
