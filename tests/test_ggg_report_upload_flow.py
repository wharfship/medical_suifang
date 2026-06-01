import unittest
from unittest.mock import patch

import pandas as pd

import ggg
from state_tracking import FieldStateTracker


class ReportUploadAdvanceTests(unittest.TestCase):
    def setUp(self):
        self.original_tracker = ggg.tracker
        self.original_metadata = ggg.metadata
        self.original_field_attempts = dict(ggg.field_attempts)

    def tearDown(self):
        ggg.tracker = self.original_tracker
        ggg.metadata = self.original_metadata
        ggg.field_attempts.clear()
        ggg.field_attempts.update(self.original_field_attempts)

    def test_advance_after_report_upload_marks_current_field_and_moves_to_next_question(self):
        metadata = {
            "血生化：血清肌酐": {
                "描述": "记录最近一次血生化结果",
                "示例": "",
                "依赖": {},
                "追问上限": 1,
            },
            "下一题": {
                "描述": "继续下一题",
                "示例": "",
                "依赖": {},
                "追问上限": 1,
            },
        }
        ggg.metadata = metadata
        ggg.tracker = FieldStateTracker(metadata)
        ggg.field_attempts.clear()
        ggg.field_attempts["血生化：血清肌酐"] = 1

        with patch("ggg.export_tracker_data", return_value=(pd.DataFrame(), "fake.xlsx")), patch(
            "ggg.build_progress_html", return_value="<progress>"
        ), patch("ggg.generate_question", return_value="下一题问题？"):
            updated_history, current_field, progress_text, parse_text, file_path, _ = (
                ggg.advance_after_report_upload([])
            )

        self.assertEqual(ggg.tracker.get_field_value("血生化：血清肌酐"), "已上传化验单")
        self.assertEqual(current_field, "下一题")
        self.assertEqual(updated_history[-1]["content"], "下一题问题？")
        self.assertNotIn("血生化：血清肌酐", ggg.field_attempts)
        self.assertEqual(progress_text, "<progress>")
        self.assertEqual(file_path, "fake.xlsx")
        self.assertIn("已上传化验单", parse_text)

    def test_save_uploaded_report_returns_download_path_for_auto_download(self):
        with patch("ggg.run_report_upload_flow", return_value=("提取完成", "C:/temp/report.xlsx")):
            status, saved_path, download_path = ggg.save_uploaded_report("C:/temp/report.jpg")

        self.assertEqual(status, "提取完成")
        self.assertEqual(saved_path, "C:/temp/report.xlsx")
        self.assertEqual(download_path, "C:/temp/report.xlsx")


if __name__ == "__main__":
    unittest.main()
