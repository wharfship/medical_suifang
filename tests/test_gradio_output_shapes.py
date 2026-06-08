import unittest
from unittest import mock

import gradio as gr
import pandas as pd

import ggg
from state_tracking import FieldStateTracker


class GradioOutputShapeTests(unittest.TestCase):
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

    def test_process_user_input_passes_missing_slots_hint_to_generate_question(self):
        chat_history = []
        captured_calls = []

        def fake_generate_question(field, metadata, history, status="first_ask", missing_slots_hint="", followup_target=None):
            captured_calls.append(
                {
                    "field": field,
                    "status": status,
                    "missing_slots_hint": missing_slots_hint,
                    "followup_target": followup_target,
                }
            )
            return "继续追问"

        parse_result = {
            "status": "done",
            "completion": "complete",
            "field_value": "吃硝苯地平，规格不清楚，一天两次，血压大概130/80",
            "confidence": 1.0,
            "reasoning": "模型先判定完成",
            "evidence": "patient: 吃硝苯地平，规格不清楚，一天两次，血压大概130/80",
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
            ggg.process_user_input("我吃硝苯地平，规格不清楚，一天两次，血压大概130/80", chat_history)

        self.assertEqual(captured_calls[-1]["status"], "ask_again")
        self.assertIn("单次剂量=缺", captured_calls[-1]["missing_slots_hint"])
        self.assertIn("仍需追问", captured_calls[-1]["missing_slots_hint"])
        self.assertEqual(captured_calls[-1]["followup_target"]["kind"], "group")
        self.assertEqual(captured_calls[-1]["followup_target"]["group"], "medication_detail")
        self.assertEqual(captured_calls[-1]["followup_target"]["missing_slots"], ["dose_each_time"])

    def test_generate_question_uses_grouped_medication_detail_prompt(self):
        question = ggg.generate_question(
            "（若有高血压）药物控制方案",
            {
                "（若有高血压）药物控制方案": {
                    "描述": "记录高血压药物控制方案",
                    "示例": "",
                    "依赖": {},
                }
            },
            [],
            status="ask_again",
            missing_slots_hint="",
            followup_target={
                "kind": "group",
                "group": "medication_detail",
                "missing_slots": ["spec", "frequency", "dose_each_time"],
            },
        )

        self.assertEqual(question, "这个药的规格是多少？一天吃几次？一次吃几片或几粒？")

    def test_process_user_input_passes_followup_target_to_generate_question(self):
        chat_history = []
        captured_calls = []

        def fake_generate_question(field, metadata, history, status="first_ask", missing_slots_hint="", followup_target=None):
            captured_calls.append(followup_target)
            return "继续追问"

        parse_result = {
            "status": "done",
            "completion": "complete",
            "field_value": "吃硝苯地平，血压还可以",
            "confidence": 1.0,
            "reasoning": "模型先判定完成",
            "evidence": "patient: 吃硝苯地平，血压还可以",
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
            ggg.process_user_input("吃硝苯地平，血压还可以", chat_history)

        self.assertEqual(captured_calls[-1]["kind"], "group")
        self.assertEqual(captured_calls[-1]["missing_slots"], ["spec", "frequency", "dose_each_time"])

    def test_strict_followup_merges_prior_partial_field_value(self):
        merged = ggg.merge_strict_followup_value(
            "（若有高血压）药物控制方案",
            "吃硝苯地平",
            "一天两次",
        )

        self.assertIn("吃硝苯地平", merged)
        self.assertIn("一天两次", merged)

    def test_process_user_input_uses_accumulated_value_for_followup_selection(self):
        chat_history = []
        captured_calls = []

        def fake_generate_question(field, metadata, history, status="first_ask", missing_slots_hint="", followup_target=None):
            captured_calls.append(followup_target)
            return "继续追问"

        metadata = {
            "（若有高血压）药物控制方案": {
                "描述": "记录高血压药物控制方案",
                "示例": "",
                "依赖": {},
            }
        }

        ggg.metadata = metadata
        ggg.tracker = FieldStateTracker(metadata)
        ggg.tracker.filled_data["（若有高血压）药物控制方案"] = {
            "value": "吃硝苯地平",
            "evidence": "",
            "status": "ask_again",
            "completion": "partial",
            "reasoning": "",
        }
        ggg.tracker.pending_fields = ["（若有高血压）药物控制方案"]
        ggg.chat_history.clear()
        ggg.field_attempts.clear()

        parse_result = {
            "status": "ask_again",
            "completion": "partial",
            "field_value": "一天两次",
            "confidence": 1.0,
            "reasoning": "补充了部分信息",
            "evidence": "patient: 一天两次",
        }

        with mock.patch.object(ggg, "parse_answer", return_value=parse_result), mock.patch.object(
            ggg, "generate_question", side_effect=fake_generate_question
        ), mock.patch.object(ggg, "export_tracker_data", return_value=(pd.DataFrame(), "medical_data.xlsx")):
            ggg.process_user_input("一天两次", chat_history)

        self.assertEqual(captured_calls[-1]["kind"], "group")
        self.assertEqual(captured_calls[-1]["missing_slots"], ["spec", "dose_each_time"])


if __name__ == "__main__":
    unittest.main()
