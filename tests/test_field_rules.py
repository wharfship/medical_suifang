import unittest

import field_rules


class FieldRuleTests(unittest.TestCase):
    def test_complex_field_done_result_is_left_unchanged(self):
        result = {
            "status": "done",
            "completion": "complete",
            "field_value": "服用硝苯地平，血压控制还可以",
            "confidence": 1.0,
            "reasoning": "模型先判定完成",
            "evidence": "patient: 服用硝苯地平，血压控制还可以",
        }

        adjusted = field_rules.apply_field_completion_rules("（若有高血压）药物控制方案", result)

        self.assertEqual(adjusted["status"], "done")
        self.assertEqual(adjusted["completion"], "complete")
        self.assertEqual(adjusted["field_value"], result["field_value"])

    def test_complex_field_partial_result_is_left_unchanged(self):
        result = {
            "status": "ask_again",
            "completion": "partial",
            "field_value": "吃硝苯地平，规格不清楚，一天两次，一次一片，平时血压大概130/80",
            "confidence": 1.0,
            "reasoning": "仍有缺失",
            "evidence": "patient: 吃硝苯地平，规格不清楚，一天两次，一次一片，平时血压大概130/80",
        }

        adjusted = field_rules.apply_field_completion_rules("（若有高血压）药物控制方案", result)

        self.assertEqual(adjusted["status"], "ask_again")
        self.assertEqual(adjusted["completion"], "partial")
        self.assertEqual(adjusted["field_value"], result["field_value"])

    def test_kidney_ultrasound_still_allows_relaxed_text_completion(self):
        result = {
            "status": "ask_again",
            "completion": "partial",
            "field_value": "肾脏彩超正常",
            "confidence": 1.0,
            "reasoning": "原始结果",
            "evidence": "patient: 肾脏彩超正常",
        }

        adjusted = field_rules.apply_field_completion_rules("肾脏彩超", result)

        self.assertEqual(adjusted["status"], "done")
        self.assertEqual(adjusted["completion"], "complete")


if __name__ == "__main__":
    unittest.main()
