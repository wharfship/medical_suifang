import unittest
from unittest import mock

import pandas as pd

import ggg


class GradioOutputShapeTests(unittest.TestCase):
    def test_init_system_returns_all_declared_load_outputs(self):
        with mock.patch.object(ggg, "generate_question", return_value="测试问题"):
            result = ggg.init_system()

        self.assertEqual(len(result), 11)

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


if __name__ == "__main__":
    unittest.main()
