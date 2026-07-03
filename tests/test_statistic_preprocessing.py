import unittest

from statistic_preprocessing import load_excel_template


class StatisticPreprocessingTests(unittest.TestCase):
    def test_load_excel_template_injects_cerebrovascular_sequelae_field(self):
        metadata = load_excel_template("子问题.xls")

        self.assertIn("（若曾患脑血管病）后遗症情况", metadata)
        self.assertEqual(
            metadata["（若曾患脑血管病）后遗症情况"]["依赖"],
            {"parent": "是否曾患脑血管病", "condition": ["是"]},
        )
        self.assertIn("肢体活动障碍", metadata["（若曾患脑血管病）后遗症情况"]["示例"])

    def test_load_excel_template_injects_other_history_diagnosis_field(self):
        metadata = load_excel_template("子问题.xls")

        self.assertIn("（若有其余病史）具体疾病名称", metadata)
        self.assertEqual(
            metadata["（若有其余病史）具体疾病名称"]["依赖"],
            {"parent": "其余病史及用药情况", "condition": ["是"]},
        )
        self.assertIn("明确诊断名称", metadata["（若有其余病史）具体疾病名称"]["描述"])


if __name__ == "__main__":
    unittest.main()
