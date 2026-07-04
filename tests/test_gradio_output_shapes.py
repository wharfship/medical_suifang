import tempfile
import unittest
from datetime import date as real_date
from pathlib import Path
from unittest import mock

import gradio as gr
import pandas as pd

import ggg
from state_tracking import FieldStateTracker


class GradioOutputShapeTests(unittest.TestCase):
    def test_snapshot_session_state_preserves_student_id_and_followup_date(self):
        original_student_id = getattr(ggg, "ACTIVE_STUDENT_ID", "")
        original_followup_date = getattr(ggg, "ACTIVE_FOLLOWUP_DATE", "")
        original_patient_name = ggg.PATIENT_NAME
        try:
            ggg.PATIENT_NAME = ggg.DEFAULT_PATIENT_NAME
            ggg.ACTIVE_STUDENT_ID = "30291834"
            ggg.ACTIVE_FOLLOWUP_DATE = "2025.06.12"

            state = ggg.snapshot_session_state()

            self.assertEqual(state["patient_name"], ggg.DEFAULT_PATIENT_NAME)
            self.assertEqual(state["student_id"], "30291834")
            self.assertEqual(state["followup_date"], "2025.06.12")
        finally:
            ggg.PATIENT_NAME = original_patient_name
            ggg.ACTIVE_STUDENT_ID = original_student_id
            ggg.ACTIVE_FOLLOWUP_DATE = original_followup_date

    def test_download_data_uses_session_followup_date_for_export(self):
        session_state = ggg.build_session_state(ggg.DEFAULT_PATIENT_NAME, "30291834")
        session_state["followup_date"] = "2025.06.12"

        with mock.patch.object(ggg, "export_tracker_data", return_value=(pd.DataFrame(), "medical_data.xlsx")), mock.patch.object(
            ggg, "format_excel", return_value=True
        ) as format_mock, mock.patch("ggg.os.path.exists", return_value=False), mock.patch.object(ggg, "persist_followup_export") as persist_mock:
            output_path = ggg.download_data(session_state, ggg.DEFAULT_PATIENT_NAME)

        self.assertEqual(output_path, "medical_data.xlsx")
        format_mock.assert_called_once()
        persist_mock.assert_not_called()

    def test_start_followup_keeps_message_box_update_shape(self):
        with mock.patch.object(ggg, "generate_question", return_value="测试问题"), mock.patch.object(
            ggg, "export_tracker_data", return_value=(pd.DataFrame(), "medical_data.xlsx")
        ):
            result = ggg.start_followup({}, ggg.DEFAULT_PATIENT_NAME, "30291834")

        self.assertEqual(
            result[-1],
            gr.update(
                placeholder=ggg.DEFAULT_INPUT_PLACEHOLDER,
                interactive=True,
            ),
        )

    def test_resolve_followup_date_defaults_to_today(self):
        class FakeDate:
            @staticmethod
            def today():
                return real_date(2026, 7, 4)

        with mock.patch.object(ggg, "date", FakeDate):
            self.assertEqual(ggg.resolve_followup_date(""), "2026.07.04")

    def test_build_runtime_error_message_simplifies_missing_api_text(self):
        self.assertEqual(
            ggg.build_runtime_error_message(RuntimeError("Missing DASHSCOPE_API_KEY")),
            "当前未提供API",
        )

    def test_export_tracker_data_hides_children_after_parent_summary_generated(self):
        metadata = {
            "（若有高血压）药物使用情况": {"描述": "", "示例": "", "依赖": {}},
            "（若有高血压）目前控制情况": {"描述": "", "示例": "", "依赖": {}},
            "（若有高血压）药物控制方案": {"描述": "", "示例": "", "依赖": {}},
            "当前有无糖尿病": {"描述": "", "示例": "", "依赖": {}},
        }

        ggg.metadata = metadata
        ggg.tracker = FieldStateTracker(metadata)
        ggg.chat_history.clear()
        ggg.field_attempts.clear()
        ggg.tracker.update_field(
            "（若有高血压）药物使用情况",
            {
                "status": "done",
                "completion": "complete",
                "field_value": "硝苯地平 30mg，一天一次，一次一片",
                "evidence": "patient: 一直吃硝苯地平 30mg，一天一次，一次一片",
            },
        )
        ggg.tracker.update_field(
            "（若有高血压）目前控制情况",
            {
                "status": "done",
                "completion": "complete",
                "field_value": "血压约130/80mmHg，比较稳定",
                "evidence": "patient: 血压大概130/80mmHg，平时比较稳定",
            },
        )
        ggg.tracker.update_field(
            "（若有高血压）药物控制方案",
            {
                "status": "done",
                "completion": "complete",
                "field_value": "药物使用情况：硝苯地平 30mg，一天一次，一次一片；目前控制情况：血压约130/80mmHg，比较稳定",
                "evidence": "patient: 一直吃硝苯地平 30mg，一天一次，一次一片\npatient: 血压大概130/80mmHg，平时比较稳定",
            },
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            original_base_dir = ggg.BASE_DIR
            try:
                ggg.BASE_DIR = Path(temp_dir)
                with mock.patch.object(ggg, "format_excel", return_value=True):
                    df, _ = ggg.export_tracker_data()
            finally:
                ggg.BASE_DIR = original_base_dir

        exported_fields = df["填写内容"].tolist()
        self.assertIn("（若有高血压）药物控制方案", exported_fields)
        self.assertNotIn("（若有高血压）药物使用情况", exported_fields)
        self.assertNotIn("（若有高血压）目前控制情况", exported_fields)

    def test_on_edit_returns_status_update_and_download_button_update(self):
        result = ggg.on_edit(pd.DataFrame({"a": [1]}))

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], gr.update(value="Saved"))
        self.assertEqual(result[1], gr.update(value=str(ggg.get_runtime_excel_path())))


if __name__ == "__main__":
    unittest.main()
