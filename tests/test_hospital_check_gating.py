import unittest
from pathlib import Path

from state_tracking import FieldStateTracker
from statistic_preprocessing import load_excel_template
from workflow_status import normalize_parse_result


class HospitalCheckGatingTests(unittest.TestCase):
    def test_children_are_blocked_until_parent_is_affirmative(self):
        metadata = {
            "请问您最近有去医院进行检查吗？": {
                "描述": "是否最近去医院做过相关检查",
                "示例": "",
                "依赖": {},
                "追问上限": 2,
            },
            "血生化：血清肌酐": {
                "描述": "记录血清肌酐",
                "示例": "",
                "依赖": {"parent": "请问您最近有去医院进行检查吗？", "condition": ["是"]},
                "追问上限": 3,
            },
            "尿常规：尿蛋白、尿潜血": {
                "描述": "记录尿常规",
                "示例": "",
                "依赖": {"parent": "请问您最近有去医院进行检查吗？", "condition": ["是"]},
                "追问上限": 3,
            },
            "肾脏彩超": {
                "描述": "记录肾脏彩超",
                "示例": "",
                "依赖": {"parent": "请问您最近有去医院进行检查吗？", "condition": ["是"]},
                "追问上限": 3,
            },
        }
        tracker = FieldStateTracker(metadata)

        self.assertEqual(tracker.get_next_field(), "请问您最近有去医院进行检查吗？")

        tracker.update_field("请问您最近有去医院进行检查吗？", {"field_value": "否"})
        self.assertIsNone(tracker.get_next_field())

    def test_children_become_reachable_after_affirmative_parent(self):
        metadata = {
            "请问您最近有去医院进行检查吗？": {
                "描述": "是否最近去医院做过相关检查",
                "示例": "",
                "依赖": {},
                "追问上限": 2,
            },
            "血生化：血清肌酐": {
                "描述": "记录血清肌酐",
                "示例": "",
                "依赖": {"parent": "请问您最近有去医院进行检查吗？", "condition": ["是"]},
                "追问上限": 3,
            },
        }
        tracker = FieldStateTracker(metadata)
        tracker.update_field("请问您最近有去医院进行检查吗？", {"field_value": "是"})

        self.assertEqual(tracker.get_next_field(), "血生化：血清肌酐")

    def test_normalize_parse_result_keeps_noncanonical_status_default_behavior(self):
        result = normalize_parse_result({"status": "unknown", "field_value": "去过", "confidence": 1})
        self.assertEqual(result["status"], "ask_again")

    def test_last_questions_template_adds_parent_gate_for_hospital_checks(self):
        metadata = load_excel_template(str(Path(__file__).resolve().parents[1] / "最后几个问题.xls"))

        self.assertIn("请问您最近有去医院进行检查吗？", metadata)
        self.assertEqual(
            metadata["请问您最近有去医院进行检查吗？"]["示例"],
            "请问您最近有去医院进行检查吗？",
        )
        self.assertEqual(
            metadata["血生化：血清肌酐"]["依赖"],
            {"parent": "请问您最近有去医院进行检查吗？", "condition": ["是"]},
        )
        self.assertEqual(
            metadata["尿常规：尿蛋白、尿潜血"]["依赖"],
            {"parent": "请问您最近有去医院进行检查吗？", "condition": ["是"]},
        )
        self.assertEqual(
            metadata["肾脏彩超"]["依赖"],
            {"parent": "请问您最近有去医院进行检查吗？", "condition": ["是"]},
        )

    def test_loaded_examples_keep_status_override_and_read_check_fields_from_excel(self):
        metadata = load_excel_template(str(Path(__file__).resolve().parents[1] / "最后几个问题.xls"))

        self.assertEqual(
            metadata["随访时受者状态"]["示例"],
            "请告诉我最近一次检查中您的受者状态。A:移植肾功能正常（在检查医院肌酐指标的正常范围内）  B:移植肾功能不全（高于检查医院肌酐指标的正常范围） C:恢复透析（受者恢复透析状态） D：受者死亡",
        )
        self.assertIn("第一次提问必须问", metadata["血生化：血清肌酐"]["示例"])

    def test_parent_gate_field_normalizes_affirmative_variants(self):
        raw = {
            "field": "请问您最近有去医院进行检查吗？",
            "status": "done",
            "completion": "complete",
            "field_value": "上个月去医院复查过",
            "confidence": 1.0,
            "reasoning": "模型判断已回答",
            "evidence": "patient: 上个月去医院复查过",
        }

        adjusted = normalize_parse_result(raw)
        self.assertEqual(adjusted["field_value"], "是")

    def test_parent_gate_field_normalizes_negative_and_unknown_variants(self):
        negative = {
            "field": "请问您最近有去医院进行检查吗？",
            "status": "done",
            "completion": "complete",
            "field_value": "最近没去医院检查",
            "confidence": 1.0,
            "reasoning": "模型判断已回答",
            "evidence": "patient: 最近没去医院检查",
        }
        unknown = {
            "field": "请问您最近有去医院进行检查吗？",
            "status": "done",
            "completion": "complete",
            "field_value": "不太清楚，记不清了",
            "confidence": 1.0,
            "reasoning": "模型判断已回答",
            "evidence": "patient: 不太清楚，记不清了",
        }

        self.assertEqual(normalize_parse_result(negative)["field_value"], "否")
        self.assertEqual(normalize_parse_result(unknown)["field_value"], "未知")


if __name__ == "__main__":
    unittest.main()
