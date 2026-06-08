import unittest
from pathlib import Path

from statistic_preprocessing import load_excel_template


class AttemptLimitConfigTests(unittest.TestCase):
    def test_last_questions_attempt_limits_match_expected_config(self):
        metadata = load_excel_template(str(Path(__file__).resolve().parents[1] / "最后几个问题.xls"))

        self.assertEqual(metadata["血生化：血清肌酐"]["追问上限"], 3)
        self.assertEqual(metadata["尿常规：尿蛋白、尿潜血"]["追问上限"], 3)
        self.assertEqual(metadata["肾脏彩超"]["追问上限"], 3)
        self.assertEqual(metadata["近一年是否存在手术切口疼痛"]["追问上限"], 2)
        self.assertEqual(metadata["（若存在手术切口疼痛）疼痛程度评分"]["追问上限"], 2)
        self.assertEqual(metadata["（若存在手术切口疼痛）手术切口疼痛持续时间"]["追问上限"], 2)


if __name__ == "__main__":
    unittest.main()
