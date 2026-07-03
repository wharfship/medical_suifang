import unittest
from unittest.mock import patch

import gradio as gr
import os
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

    def test_advance_after_report_upload_prefills_creatinine_value_from_report_rows(self):
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
        rows = [
            {
                "item_name": "肌酐（酶法）",
                "abbr": "CREA",
                "result": "66",
                "unit": "umol/L",
                "reference_range": "41-81",
            }
        ]

        with patch("ggg.export_tracker_data", return_value=(pd.DataFrame(), "fake.xlsx")), patch(
            "ggg.build_progress_html", return_value="<progress>"
        ), patch("ggg.generate_question", return_value="下一题问题？"):
            updated_history, current_field, progress_text, parse_text, file_path, _ = (
                ggg.advance_after_report_upload([], rows)
            )

        self.assertEqual(ggg.tracker.get_field_value("血生化：血清肌酐"), "66")
        self.assertEqual(current_field, "下一题")
        self.assertEqual(updated_history[-1]["content"], "下一题问题？")
        self.assertEqual(progress_text, "<progress>")
        self.assertEqual(file_path, "fake.xlsx")
        self.assertIn("66", parse_text)

    def test_advance_after_report_upload_prefills_urine_summary_from_report_rows(self):
        metadata = {
            "尿常规：尿蛋白、尿潜血": {
                "描述": "记录最近一次尿常规结果",
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
        rows = [
            {
                "item_name": "潜血",
                "abbr": "BLD",
                "result": "Trace-Lysed",
                "unit": "",
                "reference_range": "-",
            },
            {
                "item_name": "蛋白质",
                "abbr": "PRO",
                "result": "Trace",
                "unit": "g/L",
                "reference_range": "-",
            },
        ]

        with patch("ggg.export_tracker_data", return_value=(pd.DataFrame(), "fake.xlsx")), patch(
            "ggg.build_progress_html", return_value="<progress>"
        ), patch("ggg.generate_question", return_value="下一题问题？"):
            _, current_field, _, parse_text, _, _ = ggg.advance_after_report_upload([], rows)

        self.assertEqual(ggg.tracker.get_field_value("尿常规：尿蛋白、尿潜血"), "尿潜血：Trace-Lysed；尿蛋白：Trace")
        self.assertEqual(current_field, "下一题")
        self.assertIn("尿潜血：Trace-Lysed；尿蛋白：Trace", parse_text)

    def test_advance_after_report_upload_marks_kidney_ultrasound_as_uploaded(self):
        metadata = {
            "肾脏彩超": {
                "描述": "记录肾脏彩超结果",
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

        with patch("ggg.export_tracker_data", return_value=(pd.DataFrame(), "fake.xlsx")), patch(
            "ggg.build_progress_html", return_value="<progress>"
        ), patch("ggg.generate_question", return_value="下一题问题？"):
            _, current_field, _, parse_text, _, _ = ggg.advance_after_report_upload([], [])

        self.assertEqual(ggg.tracker.get_field_value("肾脏彩超"), "已上传肾脏彩超")
        self.assertEqual(current_field, "下一题")
        self.assertIn("已上传肾脏彩超", parse_text)

    def test_save_uploaded_report_returns_download_path_and_resets_uploader(self):
        with patch(
            "ggg.run_report_upload_flow_with_rows",
            return_value=("提取完成", "C:/temp/report.xlsx", [{"item_name": "肌酐（酶法）", "result": "66"}]),
        ):
            status, saved_path, download_path, upload_reset, rows = ggg.save_uploaded_report(
                "C:/temp/report.jpg",
                current_field="血生化：血清肌酐",
            )

        self.assertEqual(status, "提取完成，已用于当前题：血生化：血清肌酐")
        self.assertEqual(saved_path, "C:/temp/report.xlsx")
        self.assertEqual(download_path, "C:/temp/report.xlsx")
        self.assertEqual(upload_reset, gr.update(value=None))
        self.assertEqual(rows, [{"item_name": "肌酐（酶法）", "result": "66"}])

    def test_save_uploaded_report_for_kidney_ultrasound_saves_original_only(self):
        with patch(
            "ggg.save_report_file_only",
            return_value=("上传完成", "C:/outputs/李同学/ultrasound.jpg"),
        ) as save_only_mock:
            status, saved_path, download_path, upload_reset, rows = ggg.save_uploaded_report(
                "C:/temp/ultrasound.jpg",
                current_field="肾脏彩超",
            )

        save_only_mock.assert_called_once()
        args, kwargs = save_only_mock.call_args
        self.assertEqual(os.path.normpath(args[0]), os.path.normpath("C:/temp/ultrasound.jpg"))
        self.assertEqual(kwargs, {"patient_name": ggg.PATIENT_NAME, "student_id": "", "field_name": "肾脏彩超"})
        self.assertEqual(status, "上传完成，已用于当前题：肾脏彩超")
        self.assertEqual(saved_path, "C:/outputs/李同学/ultrasound.jpg")
        self.assertIsNone(download_path)
        self.assertEqual(upload_reset, gr.update(value=None))
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
