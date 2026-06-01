import unittest

from ggg import ALLOWED_REPORT_FILE_TYPES, ALLOWED_REPORT_SUFFIXES


class UploadConfigTests(unittest.TestCase):
    def test_upload_accepts_only_supported_report_types(self):
        self.assertEqual(
            ALLOWED_REPORT_SUFFIXES,
            {".docx", ".png", ".jpg", ".jpeg"},
        )
        self.assertEqual(
            ALLOWED_REPORT_FILE_TYPES,
            [".docx", ".png", ".jpg", ".jpeg"],
        )


if __name__ == "__main__":
    unittest.main()
