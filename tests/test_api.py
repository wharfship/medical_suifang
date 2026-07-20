import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import create_app
from followup_api_service import FollowupWorkflow


def build_metadata(*fields):
    return {
        field: {"描述": f"{field}描述", "示例": "", "依赖": {}, "追问上限": 2}
        for field in fields
    }


class FollowupApiTests(unittest.TestCase):
    def setUp(self):
        self.workflow = FollowupWorkflow(
            metadata_factory=lambda: build_metadata("当前有无高血压", "下一题"),
        )
        self.client = TestClient(create_app(self.workflow))

    def tearDown(self):
        self.client.close()

    @patch("followup_api_service.generate_question", side_effect=lambda field, *_: f"{field}？")
    def test_create_and_get_followup(self, _):
        response = self.client.post(
            "/api/v1/followups",
            json={"patient_name": "张三", "student_id": "20260001"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "in_progress")
        self.assertEqual(payload["question"], "当前有无高血压？")
        self.assertNotIn("followup_date", payload)

        restored = self.client.get(f"/api/v1/followups/{payload['followup_id']}")
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.json()["messages"], payload["messages"])

    @patch("followup_api_service.generate_question", side_effect=lambda field, *_: f"{field}？")
    @patch(
        "followup_api_service.parse_answer",
        return_value={
            "status": "done",
            "completion": "complete",
            "field_value": "无",
            "confidence": 0.95,
            "reasoning": "明确否认",
            "evidence": "patient: 没有",
        },
    )
    def test_message_advances_workflow(self, _, __):
        created = self.client.post(
            "/api/v1/followups",
            json={"patient_name": "张三", "student_id": "20260001"},
        ).json()

        response = self.client.post(
            f"/api/v1/followups/{created['followup_id']}/messages",
            json={"content": "没有"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["parsed_result"]["field_value"], "否")
        self.assertEqual(payload["current_field"]["label"], "下一题")
        self.assertEqual(payload["question"], "下一题？")

    @patch("followup_api_service.generate_question", side_effect=lambda field, *_: f"{field}？")
    @patch(
        "followup_api_service.parse_answer",
        return_value={
            "status": "ask_again",
            "completion": "empty",
            "field_value": "",
            "confidence": 0.2,
            "reasoning": "信息不足",
            "evidence": "patient: 不知道",
        },
    )
    def test_attempt_limit_returns_the_finalized_result(self, _, __):
        workflow = FollowupWorkflow(
            metadata_factory=lambda: {
                "当前有无高血压": {
                    "描述": "判断是否有高血压",
                    "示例": "",
                    "依赖": {},
                    "追问上限": 1,
                },
                "下一题": {"描述": "下一题", "示例": "", "依赖": {}, "追问上限": 1},
            },
        )
        client = TestClient(create_app(workflow))
        self.addCleanup(client.close)
        created = client.post(
            "/api/v1/followups",
            json={"patient_name": "张三", "student_id": "20260001"},
        ).json()

        response = client.post(
            f"/api/v1/followups/{created['followup_id']}/messages",
            json={"content": "不知道"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["parsed_result"]["status"], "done")
        self.assertEqual(response.json()["current_field"]["label"], "下一题")

    @patch("followup_api_service.generate_question", side_effect=lambda field, *_: f"{field}？")
    @patch(
        "followup_api_service.extract_lab_items_from_file",
        return_value=[
            {
                "item_name": "肌酐",
                "abbr": "CREA",
                "result": "66",
                "unit": "umol/L",
                "reference_range": "41-81",
            }
        ],
    )
    def test_report_extracts_and_advances_workflow(self, _, __):
        workflow = FollowupWorkflow(
            metadata_factory=lambda: build_metadata("血生化：血清肌酐", "下一题"),
        )
        client = TestClient(create_app(workflow))
        self.addCleanup(client.close)
        created = client.post(
            "/api/v1/followups",
            json={"patient_name": "张三", "student_id": "20260001"},
        ).json()

        response = client.post(
            f"/api/v1/followups/{created['followup_id']}/reports",
            files={"file": ("lab.jpg", b"image-bytes", "image/jpeg")},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["rows"][0]["result"], "66")
        self.assertEqual(payload["parsed_result"]["field_value"], "66")
        self.assertEqual(payload["current_field"]["label"], "下一题")

    @patch("followup_api_service.generate_question", side_effect=lambda field, *_: f"{field}？")
    @patch(
        "followup_api_service.parse_answer",
        return_value={
            "status": "done",
            "completion": "complete",
            "field_value": "无",
            "confidence": 0.95,
            "reasoning": "明确否认",
            "evidence": "patient: 没有",
        },
    )
    def test_completed_followup_saves_final_excel_to_outputs(self, _, __):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "outputs"
            workflow = FollowupWorkflow(
                metadata_factory=lambda: build_metadata("当前有无高血压"),
                output_dir=output_dir,
            )
            client = TestClient(create_app(workflow))
            self.addCleanup(client.close)
            created = client.post(
                "/api/v1/followups",
                json={"patient_name": "张三", "student_id": "20260001"},
            ).json()

            response = client.post(
                f"/api/v1/followups/{created['followup_id']}/messages",
                json={"content": "没有"},
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "finished")
            patient_dir = output_dir / "张三_20260001"
            result_dirs = [path for path in patient_dir.iterdir() if path.is_dir()]
            self.assertEqual(len(result_dirs), 1)
            self.assertTrue((result_dirs[0] / "medical_data.xlsx").exists())
            self.assertTrue((patient_dir / "汇总结果.xlsx").exists())

    def test_validation_and_unknown_session_errors(self):
        invalid = self.client.post(
            "/api/v1/followups",
            json={"patient_name": "A", "student_id": "12"},
        )
        self.assertEqual(invalid.status_code, 400)

        date_override = self.client.post(
            "/api/v1/followups",
            json={"patient_name": "张三", "student_id": "20260001", "followup_date": "2026-07-20"},
        )
        self.assertEqual(date_override.status_code, 422)

        missing = self.client.get("/api/v1/followups/not-found")
        self.assertEqual(missing.status_code, 404)

        health = self.client.get("/api/v1/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
