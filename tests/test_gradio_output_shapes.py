import unittest
from unittest import mock
import tempfile
from pathlib import Path

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
            ggg.PATIENT_NAME = "李同学"
            ggg.ACTIVE_STUDENT_ID = "30291834"
            ggg.ACTIVE_FOLLOWUP_DATE = "2025.06.12"

            state = ggg.snapshot_session_state()

            self.assertEqual(state["patient_name"], "李同学")
            self.assertEqual(state["student_id"], "30291834")
            self.assertEqual(state["followup_date"], "2025.06.12")
        finally:
            ggg.PATIENT_NAME = original_patient_name
            ggg.ACTIVE_STUDENT_ID = original_student_id
            ggg.ACTIVE_FOLLOWUP_DATE = original_followup_date

    def test_download_data_uses_session_followup_date_for_export(self):
        session_state = ggg.build_session_state("李同学", "30291834")
        session_state["followup_date"] = "2025.06.12"

        with mock.patch.object(ggg, "export_tracker_data", return_value=(pd.DataFrame(), "medical_data.xlsx")), mock.patch.object(
            ggg, "persist_followup_export", return_value="fake-output.xlsx"
        ) as persist_mock, mock.patch("ggg.os.path.exists", return_value=False):
            output_path = ggg.download_data(session_state, "李同学")

        self.assertEqual(output_path, "fake-output.xlsx")
        persist_mock.assert_called_once()
        self.assertEqual(persist_mock.call_args.kwargs["patient_name"], "李同学")
        self.assertEqual(persist_mock.call_args.kwargs["student_id"], "30291834")
        self.assertEqual(persist_mock.call_args.kwargs["followup_date"], "2025.06.12")

    def test_maybe_finalize_computed_fields_auto_fills_summary_parent_field(self):
        metadata = {
            "（若有糖尿病）药物使用情况": {"描述": "", "示例": "", "依赖": {}},
            "（若有糖尿病）胰岛素使用情况": {"描述": "", "示例": "", "依赖": {}},
            "（若有糖尿病）目前控制情况": {"描述": "", "示例": "", "依赖": {}},
            "（若有糖尿病）药物控制方案": {"描述": "", "示例": "", "依赖": {}},
            "是否曾患冠心病": {"描述": "", "示例": "", "依赖": {}},
        }

        ggg.metadata = metadata
        ggg.tracker = FieldStateTracker(metadata)
        ggg.chat_history.clear()
        ggg.field_attempts.clear()
        ggg.tracker.update_field(
            "（若有糖尿病）药物使用情况",
            {
                "status": "done",
                "completion": "complete",
                "field_value": "二甲双胍 0.5g，一天两次，一次一片",
                "evidence": "patient: 一直吃二甲双胍 0.5g，一天两次，一次一片",
            },
        )
        ggg.tracker.update_field(
            "（若有糖尿病）胰岛素使用情况",
            {
                "status": "done",
                "completion": "complete",
                "field_value": "甘精胰岛素，每晚一次，每次10单位",
                "evidence": "patient: 每晚打甘精胰岛素一次，每次10单位",
            },
        )
        ggg.tracker.update_field(
            "（若有糖尿病）目前控制情况",
            {
                "status": "done",
                "completion": "complete",
                "field_value": "空腹血糖约6.5mmol/L，基本稳定",
                "evidence": "patient: 空腹血糖约6.5mmol/L，基本稳定",
            },
        )
        current_chat_history = []

        with mock.patch.object(ggg, "export_tracker_data", return_value=(pd.DataFrame(), "medical_data.xlsx")):
            next_field = ggg.maybe_finalize_computed_fields(current_chat_history)

        self.assertEqual(next_field, "是否曾患冠心病")
        self.assertEqual(
            ggg.tracker.get_field_value("（若有糖尿病）药物控制方案"),
            "药物使用情况：二甲双胍 0.5g，一天两次，一次一片；胰岛素使用情况：甘精胰岛素，每晚一次，每次10单位；目前控制情况：空腹血糖约6.5mmol/L，基本稳定",
        )
        self.assertEqual(
            ggg.tracker.filled_data["（若有糖尿病）药物控制方案"]["evidence"],
            "patient: 一直吃二甲双胍 0.5g，一天两次，一次一片\n"
            "patient: 每晚打甘精胰岛素一次，每次10单位\n"
            "patient: 空腹血糖约6.5mmol/L，基本稳定",
        )
        self.assertTrue(any("（若有糖尿病）药物控制方案" in item["content"] for item in current_chat_history))

    def test_maybe_finalize_computed_fields_auto_fills_hypertension_summary_parent_field(self):
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
        current_chat_history = []

        with mock.patch.object(ggg, "export_tracker_data", return_value=(pd.DataFrame(), "medical_data.xlsx")):
            next_field = ggg.maybe_finalize_computed_fields(current_chat_history)

        self.assertEqual(next_field, "当前有无糖尿病")
        self.assertEqual(
            ggg.tracker.get_field_value("（若有高血压）药物控制方案"),
            "药物使用情况：硝苯地平 30mg，一天一次，一次一片；目前控制情况：血压约130/80mmHg，比较稳定",
        )
        self.assertEqual(
            ggg.tracker.filled_data["（若有高血压）药物控制方案"]["evidence"],
            "patient: 一直吃硝苯地平 30mg，一天一次，一次一片\n"
            "patient: 血压大概130/80mmHg，平时比较稳定",
        )
        self.assertTrue(any("（若有高血压）药物控制方案" in item["content"] for item in current_chat_history))

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

    def test_maybe_finalize_computed_fields_auto_fills_other_history_summary_parent_field(self):
        metadata = {
            "（若有其余病史）具体疾病名称": {"描述": "", "示例": "", "依赖": {}},
            "（若有其余病史）药物使用情况": {"描述": "", "示例": "", "依赖": {}},
            "（若有其余病史）手术情况": {"描述": "", "示例": "", "依赖": {}},
            "（若有其余病史）目前控制情况": {"描述": "", "示例": "", "依赖": {}},
            "（若有其余病史）请描述具体疾病、治疗方式、用药种类、用法、治疗效果": {"描述": "", "示例": "", "依赖": {}},
            "最近一年是否存在手术切口疼痛": {"描述": "", "示例": "", "依赖": {}},
        }

        ggg.metadata = metadata
        ggg.tracker = FieldStateTracker(metadata)
        ggg.chat_history.clear()
        ggg.field_attempts.clear()
        ggg.tracker.update_field(
            "（若有其余病史）具体疾病名称",
            {
                "status": "done",
                "completion": "complete",
                "field_value": "甲亢",
                "evidence": "patient: 甲亢",
            },
        )
        ggg.tracker.update_field(
            "（若有其余病史）药物使用情况",
            {
                "status": "done",
                "completion": "complete",
                "field_value": "甲巯咪唑 10mg，一天两次，一次一片",
                "evidence": "patient: 一直吃甲巯咪唑 10mg，一天两次，一次一片",
            },
        )
        ggg.tracker.update_field(
            "（若有其余病史）手术情况",
            {
                "status": "done",
                "completion": "complete",
                "field_value": "未做过相关手术",
                "evidence": "patient: 没做过相关手术",
            },
        )
        ggg.tracker.update_field(
            "（若有其余病史）目前控制情况",
            {
                "status": "done",
                "completion": "complete",
                "field_value": "症状较前好转，目前稳定",
                "evidence": "patient: 现在症状比之前好一些，基本稳定",
            },
        )
        current_chat_history = []

        with mock.patch.object(ggg, "export_tracker_data", return_value=(pd.DataFrame(), "medical_data.xlsx")):
            next_field = ggg.maybe_finalize_computed_fields(current_chat_history)

        self.assertEqual(next_field, "最近一年是否存在手术切口疼痛")
        self.assertEqual(
            ggg.tracker.get_field_value("（若有其余病史）请描述具体疾病、治疗方式、用药种类、用法、治疗效果"),
            "具体疾病名称：甲亢；药物使用情况：甲巯咪唑 10mg，一天两次，一次一片；手术情况：未做过相关手术；目前控制情况：症状较前好转，目前稳定",
        )
        self.assertEqual(
            ggg.tracker.filled_data["（若有其余病史）请描述具体疾病、治疗方式、用药种类、用法、治疗效果"]["evidence"],
            "patient: 甲亢\n"
            "patient: 一直吃甲巯咪唑 10mg，一天两次，一次一片\n"
            "patient: 没做过相关手术\n"
            "patient: 现在症状比之前好一些，基本稳定",
        )

    def test_maybe_finalize_computed_fields_auto_fills_cerebrovascular_summary_with_sequelae(self):
        metadata = {
            "（若曾患脑血管病）患病类型": {"描述": "", "示例": "", "依赖": {}},
            "（若曾患脑血管病）药物使用情况": {"描述": "", "示例": "", "依赖": {}},
            "（若曾患脑血管病）手术情况": {"描述": "", "示例": "", "依赖": {}},
            "（若曾患脑血管病）后遗症情况": {"描述": "", "示例": "", "依赖": {}},
            "（若曾患脑血管病）目前控制情况": {"描述": "", "示例": "", "依赖": {}},
            "（若曾患脑血管病）具体疾病、治疗方式及有无后遗症": {"描述": "", "示例": "", "依赖": {}},
            "其余病史及用药情况": {"描述": "", "示例": "", "依赖": {}},
        }

        ggg.metadata = metadata
        ggg.tracker = FieldStateTracker(metadata)
        ggg.chat_history.clear()
        ggg.field_attempts.clear()
        ggg.tracker.update_field(
            "（若曾患脑血管病）患病类型",
            {"status": "done", "completion": "complete", "field_value": "脑梗", "evidence": "patient: 脑梗"},
        )
        ggg.tracker.update_field(
            "（若曾患脑血管病）药物使用情况",
            {"status": "done", "completion": "complete", "field_value": "阿司匹林 100mg，每天一次", "evidence": "patient: 吃阿司匹林 100mg，每天一次"},
        )
        ggg.tracker.update_field(
            "（若曾患脑血管病）手术情况",
            {"status": "done", "completion": "complete", "field_value": "未做过相关手术", "evidence": "patient: 没做过手术"},
        )
        ggg.tracker.update_field(
            "（若曾患脑血管病）后遗症情况",
            {"status": "done", "completion": "complete", "field_value": "遗留左侧肢体活动障碍", "evidence": "patient: 现在左侧肢体活动还有点障碍"},
        )
        ggg.tracker.update_field(
            "（若曾患脑血管病）目前控制情况",
            {"status": "done", "completion": "complete", "field_value": "目前较前好转", "evidence": "patient: 现在比以前好多了"},
        )

        with mock.patch.object(ggg, "export_tracker_data", return_value=(pd.DataFrame(), "medical_data.xlsx")):
            next_field = ggg.maybe_finalize_computed_fields([])

        self.assertEqual(next_field, "其余病史及用药情况")
        self.assertEqual(
            ggg.tracker.get_field_value("（若曾患脑血管病）具体疾病、治疗方式及有无后遗症"),
            "患病类型：脑梗；药物使用情况：阿司匹林 100mg，每天一次；手术情况：未做过相关手术；后遗症情况：遗留左侧肢体活动障碍；目前控制情况：目前较前好转",
        )

    def test_export_tracker_data_hides_cerebrovascular_sequelae_child_after_parent_summary_generated(self):
        metadata = {
            "（若曾患脑血管病）患病类型": {"描述": "", "示例": "", "依赖": {}},
            "（若曾患脑血管病）药物使用情况": {"描述": "", "示例": "", "依赖": {}},
            "（若曾患脑血管病）手术情况": {"描述": "", "示例": "", "依赖": {}},
            "（若曾患脑血管病）后遗症情况": {"描述": "", "示例": "", "依赖": {}},
            "（若曾患脑血管病）目前控制情况": {"描述": "", "示例": "", "依赖": {}},
            "（若曾患脑血管病）具体疾病、治疗方式及有无后遗症": {"描述": "", "示例": "", "依赖": {}},
        }

        ggg.metadata = metadata
        ggg.tracker = FieldStateTracker(metadata)
        ggg.chat_history.clear()
        ggg.field_attempts.clear()
        ggg.tracker.update_field(
            "（若曾患脑血管病）患病类型",
            {"status": "done", "completion": "complete", "field_value": "脑梗"},
        )
        ggg.tracker.update_field(
            "（若曾患脑血管病）药物使用情况",
            {"status": "done", "completion": "complete", "field_value": "阿司匹林 100mg，每天一次"},
        )
        ggg.tracker.update_field(
            "（若曾患脑血管病）手术情况",
            {"status": "done", "completion": "complete", "field_value": "未做过相关手术"},
        )
        ggg.tracker.update_field(
            "（若曾患脑血管病）后遗症情况",
            {"status": "done", "completion": "complete", "field_value": "遗留左侧肢体活动障碍"},
        )
        ggg.tracker.update_field(
            "（若曾患脑血管病）目前控制情况",
            {"status": "done", "completion": "complete", "field_value": "目前较前好转"},
        )
        ggg.tracker.update_field(
            "（若曾患脑血管病）具体疾病、治疗方式及有无后遗症",
            {
                "status": "done",
                "completion": "complete",
                "field_value": "患病类型：脑梗；药物使用情况：阿司匹林 100mg，每天一次；手术情况：未做过相关手术；后遗症情况：遗留左侧肢体活动障碍；目前控制情况：目前较前好转",
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
        self.assertIn("（若曾患脑血管病）具体疾病、治疗方式及有无后遗症", exported_fields)
        self.assertNotIn("（若曾患脑血管病）后遗症情况", exported_fields)

    def test_export_tracker_data_hides_other_history_children_after_parent_summary_generated(self):
        metadata = {
            "（若有其余病史）具体疾病名称": {"描述": "", "示例": "", "依赖": {}},
            "（若有其余病史）药物使用情况": {"描述": "", "示例": "", "依赖": {}},
            "（若有其余病史）手术情况": {"描述": "", "示例": "", "依赖": {}},
            "（若有其余病史）目前控制情况": {"描述": "", "示例": "", "依赖": {}},
            "（若有其余病史）请描述具体疾病、治疗方式、用药种类、用法、治疗效果": {"描述": "", "示例": "", "依赖": {}},
            "最近一年是否存在手术切口疼痛": {"描述": "", "示例": "", "依赖": {}},
        }

        ggg.metadata = metadata
        ggg.tracker = FieldStateTracker(metadata)
        ggg.chat_history.clear()
        ggg.field_attempts.clear()
        ggg.tracker.update_field(
            "（若有其余病史）具体疾病名称",
            {
                "status": "done",
                "completion": "complete",
                "field_value": "甲亢",
                "evidence": "patient: 甲亢",
            },
        )
        ggg.tracker.update_field(
            "（若有其余病史）药物使用情况",
            {
                "status": "done",
                "completion": "complete",
                "field_value": "甲巯咪唑 10mg，一天两次，一次一片",
                "evidence": "patient: 一直吃甲巯咪唑 10mg，一天两次，一次一片",
            },
        )
        ggg.tracker.update_field(
            "（若有其余病史）手术情况",
            {
                "status": "done",
                "completion": "complete",
                "field_value": "未做过相关手术",
                "evidence": "patient: 没做过相关手术",
            },
        )
        ggg.tracker.update_field(
            "（若有其余病史）目前控制情况",
            {
                "status": "done",
                "completion": "complete",
                "field_value": "症状较前好转，目前稳定",
                "evidence": "patient: 现在症状比之前好一些，基本稳定",
            },
        )
        ggg.tracker.update_field(
            "（若有其余病史）请描述具体疾病、治疗方式、用药种类、用法、治疗效果",
            {
                "status": "done",
                "completion": "complete",
                "field_value": "具体疾病名称：甲亢；药物使用情况：甲巯咪唑 10mg，一天两次，一次一片；手术情况：未做过相关手术；目前控制情况：症状较前好转，目前稳定",
                "evidence": "patient: 甲亢\npatient: 一直吃甲巯咪唑 10mg，一天两次，一次一片\npatient: 没做过相关手术\npatient: 现在症状比之前好一些，基本稳定",
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
        self.assertIn("（若有其余病史）请描述具体疾病、治疗方式、用药种类、用法、治疗效果", exported_fields)
        self.assertNotIn("（若有其余病史）具体疾病名称", exported_fields)
        self.assertNotIn("（若有其余病史）药物使用情况", exported_fields)
        self.assertNotIn("（若有其余病史）手术情况", exported_fields)
        self.assertNotIn("（若有其余病史）目前控制情况", exported_fields)

    def test_init_system_returns_all_declared_load_outputs(self):
        with mock.patch.object(ggg, "generate_question", return_value="测试问题"):
            result = ggg.init_system()

        self.assertEqual(len(result), 12)
        self.assertEqual(
            result[-1],
            gr.update(placeholder=ggg.get_input_placeholder(result[2])),
        )

    def test_upload_component_updates_targeted_fields_reset_status_and_placeholder(self):
        note_update, file_update, status_update, path_update, placeholder_update = (
            ggg.build_upload_component_updates("血生化：血清肌酐", clear_values=True)
        )

        self.assertIn("这题可上传化验单辅助填写", note_update["value"])
        self.assertIn("血生化：血清肌酐", note_update["value"])
        self.assertEqual(file_update, gr.update(visible=True, value=None))
        self.assertEqual(status_update, gr.update(visible=True, value=""))
        self.assertEqual(path_update, gr.update(visible=True, value=""))
        self.assertEqual(
            placeholder_update,
            gr.update(placeholder="这题可以直接说，也可以上传化验单照片"),
        )

    def test_upload_component_updates_use_default_placeholder_for_regular_field(self):
        note_update, _, _, _, placeholder_update = ggg.build_upload_component_updates("当前身高")

        self.assertIn("现在可以上传化验单", note_update["value"])
        self.assertEqual(
            placeholder_update,
            gr.update(placeholder="请直接输入您的回答，如不清楚也可以说“不知道”"),
        )

    def test_respond_stream_yields_all_declared_submit_outputs(self):
        with mock.patch.object(
            ggg,
            "process_user_input",
            return_value=(
                "",
                [{"role": "assistant", "content": "测试回复"}],
                "当前问题",
                "50%",
                "解析结果",
                "medical_data.xlsx",
                pd.DataFrame(),
            ),
        ):
            generator = ggg.respond("你好", [])
            next(generator)
            streamed = next(generator)

        self.assertEqual(len(streamed), 13)

    def test_on_edit_returns_status_update_and_download_button_update(self):
        with mock.patch.object(ggg, "format_excel", return_value=None):
            result = ggg.on_edit(pd.DataFrame({"a": [1]}))

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], gr.update(value="Saved"))
        self.assertEqual(result[1], gr.update(value=ggg.download_data))

    def test_process_user_input_passes_ask_again_status_to_generate_question(self):
        chat_history = []
        captured_calls = []

        def fake_generate_question(field, metadata, history, status="first_ask"):
            captured_calls.append(
                {
                    "field": field,
                    "status": status,
                }
            )
            return "继续追问"

        parse_result = {
            "status": "ask_again",
            "completion": "partial",
            "field_value": "吃硝苯地平",
            "confidence": 1.0,
            "reasoning": "还需要继续追问",
            "evidence": "patient: 吃硝苯地平",
        }
        metadata = {
            "（若有高血压）药物控制方案": {
                "描述": "记录高血压药物控制方案",
                "示例": "",
                "依赖": {},
            }
        }

        with mock.patch.object(ggg, "parse_answer", return_value=parse_result), mock.patch.object(
            ggg, "generate_question", side_effect=fake_generate_question
        ), mock.patch.object(ggg, "export_tracker_data", return_value=(pd.DataFrame(), "medical_data.xlsx")):
            ggg.metadata = metadata
            ggg.tracker = FieldStateTracker(metadata)
            ggg.chat_history.clear()
            ggg.field_attempts.clear()
            ggg.process_user_input("我吃硝苯地平", chat_history)

        self.assertEqual(captured_calls[-1]["status"], "ask_again")

    def test_process_user_input_skips_summary_parent_question_after_last_child(self):
        metadata = {
            "（若有糖尿病）药物使用情况": {"描述": "", "示例": "", "依赖": {}},
            "（若有糖尿病）胰岛素使用情况": {"描述": "", "示例": "", "依赖": {}},
            "（若有糖尿病）目前控制情况": {"描述": "", "示例": "", "依赖": {}},
            "（若有糖尿病）药物控制方案": {"描述": "", "示例": "", "依赖": {}},
            "是否曾患冠心病": {"描述": "", "示例": "", "依赖": {}},
        }
        parse_result = {
            "status": "done",
            "completion": "complete",
            "field_value": "空腹血糖约6.5mmol/L，基本稳定",
            "confidence": 1.0,
            "reasoning": "已回答",
            "evidence": "patient: 空腹血糖约6.5mmol/L，基本稳定",
        }
        chat_history = []
        captured_fields = []

        def fake_generate_question(field, metadata, history, status="first_ask"):
            captured_fields.append(field)
            return f"问题：{field}"

        ggg.metadata = metadata
        ggg.tracker = FieldStateTracker(metadata)
        ggg.chat_history.clear()
        ggg.field_attempts.clear()
        ggg.tracker.update_field(
            "（若有糖尿病）药物使用情况",
            {"status": "done", "completion": "complete", "field_value": "二甲双胍 0.5g，一天两次，一次一片"},
        )
        ggg.tracker.update_field(
            "（若有糖尿病）胰岛素使用情况",
            {"status": "done", "completion": "complete", "field_value": "甘精胰岛素，每晚一次，每次10单位"},
        )

        with mock.patch.object(ggg, "parse_answer", return_value=parse_result), mock.patch.object(
            ggg, "generate_question", side_effect=fake_generate_question
        ), mock.patch.object(ggg, "export_tracker_data", return_value=(pd.DataFrame(), "medical_data.xlsx")):
            _, updated_chat_history, current_field, _, _, _, _ = ggg.process_user_input(
                "空腹血糖约6.5mmol/L，基本稳定",
                chat_history,
            )

        self.assertEqual(current_field, "是否曾患冠心病")
        self.assertEqual(captured_fields[-1], "是否曾患冠心病")
        self.assertEqual(
            ggg.tracker.get_field_value("（若有糖尿病）药物控制方案"),
            "药物使用情况：二甲双胍 0.5g，一天两次，一次一片；胰岛素使用情况：甘精胰岛素，每晚一次，每次10单位；目前控制情况：空腹血糖约6.5mmol/L，基本稳定",
        )
        self.assertFalse(any(item["content"] == "问题：（若有糖尿病）药物控制方案" for item in updated_chat_history if item["role"] == "assistant"))


if __name__ == "__main__":
    unittest.main()
