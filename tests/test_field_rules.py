import unittest

import field_rules


class StrictComplexFieldRuleTests(unittest.TestCase):
    def test_hypertension_medication_requires_all_triggered_medication_slots(self):
        result = {
            "status": "done",
            "completion": "complete",
            "field_value": "服用硝苯地平，血压控制还可以",
            "confidence": 1.0,
            "reasoning": "模型先判定完成",
            "evidence": "patient: 服用硝苯地平，血压控制还可以",
        }

        adjusted = field_rules.apply_field_completion_rules("（若有高血压）药物控制方案", result)

        self.assertEqual(adjusted["status"], "ask_again")
        self.assertEqual(adjusted["completion"], "partial")

    def test_hypertension_medication_can_finish_when_unknown_slots_are_explicit(self):
        result = {
            "status": "ask_again",
            "completion": "partial",
            "field_value": "吃硝苯地平，规格不清楚，一天两次，一次一片，平时血压大概130/80",
            "confidence": 1.0,
            "reasoning": "仍有缺失",
            "evidence": "patient: 吃硝苯地平，规格不清楚，一天两次，一次一片，平时血压大概130/80",
        }

        adjusted = field_rules.apply_field_completion_rules("（若有高血压）药物控制方案", result)

        self.assertEqual(adjusted["status"], "done")
        self.assertEqual(adjusted["completion"], "complete")

    def test_diabetes_medication_requires_control_level_and_triggered_branches(self):
        result = {
            "status": "done",
            "completion": "complete",
            "field_value": "口服二甲双胍，一天两次，一次一片",
            "confidence": 1.0,
            "reasoning": "模型先判定完成",
            "evidence": "patient: 口服二甲双胍，一天两次，一次一片",
        }

        adjusted = field_rules.apply_field_completion_rules("（若有糖尿病）药物控制方案", result)

        self.assertEqual(adjusted["status"], "ask_again")

    def test_coronary_heart_disease_treatment_requires_effect_slots(self):
        result = {
            "status": "done",
            "completion": "complete",
            "field_value": "做过支架手术，2020年做的，现在症状好多了",
            "confidence": 1.0,
            "reasoning": "模型先判定完成",
            "evidence": "patient: 做过支架手术，2020年做的，现在症状好多了",
        }

        adjusted = field_rules.apply_field_completion_rules("（若曾患冠心病）治疗方式", result)

        self.assertEqual(adjusted["status"], "ask_again")

    def test_cerebrovascular_disease_requires_sequelae_slot(self):
        result = {
            "status": "done",
            "completion": "complete",
            "field_value": "脑梗，保守治疗，现在比之前好，没有再犯",
            "confidence": 1.0,
            "reasoning": "模型先判定完成",
            "evidence": "patient: 脑梗，保守治疗，现在比之前好，没有再犯",
        }

        adjusted = field_rules.apply_field_completion_rules("（若曾患脑血管病）具体疾病、治疗方式及有无后遗症", result)

        self.assertEqual(adjusted["status"], "ask_again")

    def test_other_history_requires_treatment_effect_slot(self):
        result = {
            "status": "done",
            "completion": "complete",
            "field_value": "甲减，吃优甲乐",
            "confidence": 1.0,
            "reasoning": "模型先判定完成",
            "evidence": "patient: 甲减，吃优甲乐",
        }

        adjusted = field_rules.apply_field_completion_rules("（若有其余病史）请描述具体疾病、治疗方式、用药种类、用法、治疗效果", result)

        self.assertEqual(adjusted["status"], "ask_again")

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

    def test_build_missing_slots_hint_lists_missing_and_unknown_slots(self):
        result = {
            "status": "done",
            "completion": "complete",
            "field_value": "吃硝苯地平，规格不清楚，一天两次，血压大概130/80",
            "confidence": 1.0,
            "reasoning": "模型先判定完成",
            "evidence": "patient: 吃硝苯地平，规格不清楚，一天两次，血压大概130/80",
        }

        adjusted = field_rules.apply_field_completion_rules("（若有高血压）药物控制方案", result)
        hint = field_rules.build_missing_slots_hint("（若有高血压）药物控制方案", adjusted["field_value"])

        self.assertIn("已知", hint)
        self.assertIn("药物名称=有", hint)
        self.assertIn("规格=不知道", hint)
        self.assertIn("单次剂量=缺", hint)

    def test_build_missing_slots_payload_groups_slots_by_status(self):
        payload = field_rules.build_missing_slots_payload(
            "（若有高血压）药物控制方案",
            "吃硝苯地平，规格不清楚，一天两次，血压大概130/80",
        )

        self.assertEqual(payload["field"], "（若有高血压）药物控制方案")
        self.assertIn("药物名称", payload["answered"])
        self.assertIn("规格", payload["unknown"])
        self.assertIn("单次剂量", payload["missing"])

    def test_selects_medication_name_before_medication_detail_group(self):
        target = field_rules.get_strict_followup_target(
            "（若有高血压）药物控制方案",
            "吃药控制血压，血压还可以",
        )

        self.assertEqual(target["kind"], "slot")
        self.assertEqual(target["slot"], "drug_name")

    def test_selects_grouped_medication_detail_after_drug_name(self):
        target = field_rules.get_strict_followup_target(
            "（若有高血压）药物控制方案",
            "吃硝苯地平，血压还可以",
        )

        self.assertEqual(target["kind"], "group")
        self.assertEqual(target["group"], "medication_detail")
        self.assertEqual(target["missing_slots"], ["spec", "frequency", "dose_each_time"])

    def test_grouped_medication_detail_keeps_only_remaining_members(self):
        target = field_rules.get_strict_followup_target(
            "（若有高血压）药物控制方案",
            "吃硝苯地平，规格不清楚，一天两次，血压还可以",
        )

        self.assertEqual(target["kind"], "group")
        self.assertEqual(target["group"], "medication_detail")
        self.assertEqual(target["missing_slots"], ["dose_each_time"])

    def test_coronary_treatment_prioritizes_drug_name_before_detail_group(self):
        target = field_rules.get_strict_followup_target(
            "（若曾患冠心病）治疗方式",
            "一直吃阿司匹林",
        )

        self.assertEqual(target["kind"], "group")
        self.assertEqual(target["group"], "medication_detail")

    def test_other_history_treatment_prioritizes_missing_disease_name_before_other_branches(self):
        target = field_rules.get_strict_followup_target(
            "（若有其余病史）请描述具体疾病、治疗方式、用药种类、用法、治疗效果",
            "一直吃药，控制得还行",
        )

        self.assertEqual(target["kind"], "slot")
        self.assertEqual(target["slot"], "disease_name")


if __name__ == "__main__":
    unittest.main()
