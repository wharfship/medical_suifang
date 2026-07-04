import unittest
from unittest import mock

import gradio as gr
import pandas as pd

import ggg


class DownloadExportFlowTests(unittest.TestCase):
    def test_download_data_returns_runtime_excel_for_download_only(self):
        session_state = ggg.build_session_state(ggg.DEFAULT_PATIENT_NAME, "30291834")
        session_state["followup_date"] = "2025.06.12"

        with mock.patch.object(ggg, "get_runtime_excel_path", return_value=ggg.Path("medical_data.xlsx")), mock.patch.object(
            ggg, "format_excel", return_value=True
        ) as format_mock, mock.patch("ggg.os.path.exists", return_value=True), mock.patch.object(ggg, "export_tracker_data") as export_mock, mock.patch.object(
            ggg, "persist_followup_export"
        ) as persist_mock:
            output_path = ggg.download_data(session_state, ggg.DEFAULT_PATIENT_NAME)

        self.assertEqual(output_path, "medical_data.xlsx")
        export_mock.assert_not_called()
        format_mock.assert_called_once()
        persist_mock.assert_not_called()

    def test_persist_current_followup_output_copies_runtime_excel_into_outputs(self):
        with mock.patch.object(ggg, "persist_followup_export", return_value="fake-output.xlsx") as persist_mock, mock.patch.object(
            ggg, "get_runtime_excel_path", return_value=ggg.Path("medical_data.xlsx")
        ), mock.patch.object(ggg, "snapshot_session_state", return_value={"student_id": "30291834", "followup_date": "2025.06.12"}):
            ggg.PATIENT_NAME = ggg.DEFAULT_PATIENT_NAME
            ggg.last_report_output_path = "report.xlsx"
            output_path = ggg.persist_current_followup_output()

        self.assertEqual(output_path, "fake-output.xlsx")
        persist_mock.assert_called_once_with(
            ggg.Path("medical_data.xlsx"),
            uploaded_report_path="report.xlsx",
            patient_name=ggg.DEFAULT_PATIENT_NAME,
            student_id="30291834",
            followup_date="2025.06.12",
        )

    def test_process_user_input_persists_server_output_when_followup_completes(self):
        metadata = {
            "当前有无高血压": {"描述": "", "示例": "", "依赖": {}},
        }
        parse_result = {
            "status": "done",
            "completion": "complete",
            "field_value": "无",
            "confidence": 1.0,
            "reasoning": "已回答",
            "evidence": "patient: 没有高血压",
        }

        ggg.metadata = metadata
        ggg.tracker = ggg.FieldStateTracker(metadata)
        ggg.chat_history.clear()
        ggg.field_attempts.clear()

        with mock.patch.object(ggg, "parse_answer", return_value=parse_result), mock.patch.object(
            ggg, "export_tracker_data", return_value=(pd.DataFrame(), "medical_data.xlsx")
        ), mock.patch.object(ggg, "persist_current_followup_output", return_value="outputs/final/medical_data.xlsx") as persist_mock:
            _, updated_chat_history, current_field, _, _, _, _ = ggg.process_user_input("没有高血压", [])

        self.assertIsNone(current_field)
        persist_mock.assert_called_once_with("medical_data.xlsx")
        self.assertIn("您已可以关闭页面", updated_chat_history[-1]["content"])

    def test_build_result_component_updates_keeps_download_handler_until_followup_finishes(self):
        dataframe = pd.DataFrame({"a": [1]})

        in_progress_download, in_progress_df = ggg.build_result_component_updates("medical_data.xlsx", dataframe, "current-field")
        finished_download, finished_df = ggg.build_result_component_updates("medical_data.xlsx", dataframe, None)

        self.assertEqual(in_progress_download, gr.update(value=None, visible=False))
        self.assertEqual(in_progress_df, gr.update(value=dataframe, visible=False))
        self.assertEqual(finished_download, gr.update(value="medical_data.xlsx", visible=True))
        self.assertEqual(finished_df, gr.update(value=dataframe, visible=True))


if __name__ == "__main__":
    unittest.main()
