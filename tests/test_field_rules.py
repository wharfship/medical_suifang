import unittest

import field_rules


class FieldRuleTests(unittest.TestCase):
    def test_complex_field_done_result_is_left_unchanged_when_minimum_slots_are_present(self):
        result = {
            "status": "done",
            "completion": "complete",
            "field_value": "服用硝苯地平 30mg，每天一次，血压控制还可以",
            "confidence": 1.0,
            "reasoning": "模型先判定完成",
            "evidence": "patient: 服用硝苯地平 30mg，每天一次，血压控制还可以",
        }

        adjusted = field_rules.apply_field_completion_rules("（若有高血压）药物控制方案", result)

        self.assertEqual(adjusted["status"], "done")
        self.assertEqual(adjusted["completion"], "complete")
        self.assertEqual(adjusted["field_value"], result["field_value"])

    def test_complex_field_partial_result_stays_partial_when_spec_is_missing(self):
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

    def test_other_history_gate_field_accepts_yes_answer(self):
        result = {
            "status": "ask_again",
            "completion": "partial",
            "field_value": "有",
            "confidence": 1.0,
            "reasoning": "原始结果",
            "evidence": "patient: 有",
        }

        adjusted = field_rules.apply_field_completion_rules("其余病史及用药情况", result)

        self.assertEqual(adjusted["field_value"], "是")
        self.assertEqual(adjusted["status"], "done")

    def test_other_history_gate_field_normalizes_single_mei_to_no(self):
        result = {
            "status": "done",
            "completion": "complete",
            "field_value": "没",
            "confidence": 1.0,
            "reasoning": "原始结果",
            "evidence": "patient: 没",
        }

        adjusted = field_rules.apply_field_completion_rules("其余病史及用药情况", result)

        self.assertEqual(adjusted["field_value"], "否")
        self.assertEqual(adjusted["status"], "done")

    def test_other_history_gate_field_normalizes_direct_diagnosis_to_yes(self):
        result = {
            "status": "ask_again",
            "completion": "partial",
            "field_value": "甲减",
            "confidence": 1.0,
            "reasoning": "原始结果",
            "evidence": "patient: 甲减",
        }

        adjusted = field_rules.apply_field_completion_rules("其余病史及用药情况", result)

        self.assertEqual(adjusted["field_value"], "是")
        self.assertEqual(adjusted["status"], "done")

    def test_other_history_diagnosis_field_rejects_symptom_only_answer(self):
        result = {
            "status": "ask_again",
            "completion": "partial",
            "field_value": "头晕",
            "confidence": 1.0,
            "reasoning": "原始结果",
            "evidence": "patient: 头晕",
        }

        adjusted = field_rules.apply_field_completion_rules("（若有其余病史）疾病名称", result)

        self.assertEqual(adjusted["status"], "ask_again")
        self.assertEqual(adjusted["completion"], "partial")

    def test_other_history_diagnosis_field_accepts_specific_diagnosis(self):
        result = {
            "status": "ask_again",
            "completion": "partial",
            "field_value": "腰椎间盘突出",
            "confidence": 1.0,
            "reasoning": "原始结果",
            "evidence": "patient: 腰椎间盘突出",
        }

        adjusted = field_rules.apply_field_completion_rules("（若有其余病史）疾病名称", result)

        self.assertEqual(adjusted["status"], "done")
        self.assertEqual(adjusted["completion"], "complete")

    def test_diabetes_medication_requires_insulin_name_when_only_generic_insulin_is_given(self):
        result = {
            "status": "done",
            "completion": "complete",
            "field_value": "吃二甲双胍 0.5g，一天两次，还打胰岛素，每晚一次，每次10单位，血糖控制还可以",
            "confidence": 1.0,
            "reasoning": "模型先判定完成",
            "evidence": "patient: 吃二甲双胍 0.5g，一天两次，还打胰岛素，每晚一次，每次10单位，血糖控制还可以",
        }

        adjusted = field_rules.apply_field_completion_rules("（若有糖尿病）药物控制方案", result)

        self.assertEqual(adjusted["status"], "ask_again")
        self.assertEqual(adjusted["completion"], "partial")

    def test_cerebrovascular_treatment_requires_sequelae_detail_when_sequelae_exists(self):
        result = {
            "status": "done",
            "completion": "complete",
            "field_value": "脑梗，吃阿司匹林 100mg，每天一次，目前好转了，但还有后遗症",
            "confidence": 1.0,
            "reasoning": "模型先判定完成",
            "evidence": "patient: 脑梗，吃阿司匹林 100mg，每天一次，目前好转了，但还有后遗症",
        }

        adjusted = field_rules.apply_field_completion_rules("（若曾患脑血管病）具体疾病、治疗方式及有无后遗症", result)

        self.assertEqual(adjusted["status"], "ask_again")
        self.assertEqual(adjusted["completion"], "partial")


if __name__ == "__main__":
    unittest.main()
