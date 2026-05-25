import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import pandas as pd

from extract_demo import run_extraction
from lab_report_extractor import (
    build_display_rows,
    export_rows_to_xlsx,
    extract_first_image_payload,
    extract_lab_items_from_file,
    normalize_extracted_items,
    parse_model_response,
)


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeCompletion:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.chat = self
        self.completions = self

    def create(self, model, messages):
        self.calls.append({"model": model, "messages": messages})
        return FakeCompletion(self.responses.pop(0))


class NormalizeExtractedItemsTests(unittest.TestCase):
    def test_normalize_keeps_five_columns_and_deduplicates(self):
        rows = [
            {
                "item_name": "碱性磷酸酶",
                "abbr": "ALP",
                "result": "103",
                "unit": "U/L",
                "reference_range": "50-135",
            },
            {
                "item_name": "碱性磷酸酶",
                "abbr": "ALP",
                "result": "103",
                "unit": "U/L",
                "reference_range": "50-135",
            },
            {
                "item_name": "白蛋白",
                "abbr": "ALB",
                "result": "",
                "unit": "g/L",
                "reference_range": "40.0-55.0",
            },
        ]

        normalized = normalize_extracted_items(rows)

        self.assertEqual(
            normalized,
            [
                {
                    "item_name": "碱性磷酸酶",
                    "abbr": "ALP",
                    "result": "103",
                    "unit": "U/L",
                    "reference_range": "50-135",
                }
            ],
        )


class DisplayProjectionTests(unittest.TestCase):
    def test_build_display_rows_projects_three_columns(self):
        rows = [
            {
                "item_name": "白蛋白",
                "abbr": "ALB",
                "result": "42.1",
                "unit": "g/L",
                "reference_range": "40.0-55.0",
            }
        ]

        display_rows = build_display_rows(rows)

        self.assertEqual(
            display_rows,
            [{"项目名称": "白蛋白", "结果": "42.1", "单位": "g/L"}],
        )


class ExportRowsToXlsxTests(unittest.TestCase):
    def test_export_writes_projected_columns(self):
        rows = [
            {
                "item_name": "肌酐",
                "abbr": "Cr",
                "result": "50.4",
                "unit": "umol/L",
                "reference_range": "41.0-111.0",
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = export_rows_to_xlsx(rows, temp_dir, "sample")
            dataframe = pd.read_excel(output_path)

        self.assertEqual(list(dataframe.columns), ["项目名称", "结果", "单位"])
        self.assertEqual(
            dataframe.iloc[0].to_dict(),
            {"项目名称": "肌酐", "结果": 50.4, "单位": "umol/L"},
        )


class DocxImageExtractionTests(unittest.TestCase):
    def test_extract_first_image_payload_rejects_docx_without_media(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            docx_path = os.path.join(temp_dir, "empty.docx")
            with zipfile.ZipFile(docx_path, "w") as archive:
                archive.writestr("[Content_Types].xml", "")

            with self.assertRaisesRegex(ValueError, "未发现可提取图片"):
                extract_first_image_payload(docx_path)

    def test_extract_first_image_payload_rejects_invalid_docx_container(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            docx_path = os.path.join(temp_dir, "broken.docx")
            with open(docx_path, "wb") as handle:
                handle.write(b"not a zip payload")

            with self.assertRaisesRegex(ValueError, "docx"):
                extract_first_image_payload(docx_path)

    def test_extract_first_image_payload_uses_ole_conversion_when_header_is_legacy_word(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            docx_path = os.path.join(temp_dir, "legacy.docx")
            with open(docx_path, "wb") as handle:
                handle.write(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1legacy-word")

            converted_path = os.path.join(temp_dir, "converted.docx")
            with zipfile.ZipFile(converted_path, "w") as archive:
                archive.writestr("word/media/image1.png", b"fake-image-bytes")

            with patch(
                "lab_report_extractor.convert_legacy_word_to_docx",
                return_value=converted_path,
            ) as convert_mock:
                payload = extract_first_image_payload(docx_path)

        convert_mock.assert_called_once_with(docx_path)
        self.assertTrue(payload.startswith("data:image/png;base64,"))


class ParseModelResponseTests(unittest.TestCase):
    def test_parse_model_response_reads_five_column_json(self):
        content = """```json
{"items":[{"item_name":"肌酐","abbr":"Cr","result":"50.4","unit":"umol/L","reference_range":"41.0-111.0"}]}
```"""

        rows = parse_model_response(content)

        self.assertEqual(
            rows,
            [
                {
                    "item_name": "肌酐",
                    "abbr": "Cr",
                    "result": "50.4",
                    "unit": "umol/L",
                    "reference_range": "41.0-111.0",
                }
            ],
        )


class ExtractionFlowTests(unittest.TestCase):
    def test_extract_lab_items_retries_when_result_matches_abbreviation(self):
        first_pass = """{"items":[{"item_name":"碱性磷酸酶","abbr":"ALP","result":"ALP","unit":"U/L","reference_range":"50-135"}]}"""
        second_pass = """{"items":[{"item_name":"碱性磷酸酶","abbr":"ALP","result":"103","unit":"U/L","reference_range":"50-135"}]}"""
        client = FakeClient([first_pass, second_pass])

        with patch(
            "lab_report_extractor.extract_first_image_payload",
            return_value="data:image/png;base64,abc",
        ):
            rows = extract_lab_items_from_file("fake.docx", client=client)

        self.assertEqual(rows[0]["result"], "103")
        self.assertEqual(len(client.calls), 2)

    def test_extract_lab_items_retries_when_result_matches_unit(self):
        first_pass = """{"items":[{"item_name":"白蛋白","abbr":"ALB","result":"g/L","unit":"g/L","reference_range":"40.0-55.0"}]}"""
        second_pass = """{"items":[{"item_name":"白蛋白","abbr":"ALB","result":"42.1","unit":"g/L","reference_range":"40.0-55.0"}]}"""
        client = FakeClient([first_pass, second_pass])

        with patch(
            "lab_report_extractor.extract_first_image_payload",
            return_value="data:image/png;base64,abc",
        ):
            rows = extract_lab_items_from_file("fake.docx", client=client)

        self.assertEqual(rows[0]["result"], "42.1")
        self.assertEqual(len(client.calls), 2)


class ExtractDemoTests(unittest.TestCase):
    def test_run_extraction_returns_projected_dataframe(self):
        full_rows = [
            {
                "item_name": "白蛋白",
                "abbr": "ALB",
                "result": "42.1",
                "unit": "g/L",
                "reference_range": "40.0-55.0",
            }
        ]

        with patch("extract_demo.extract_lab_items_from_file", return_value=full_rows):
            status, dataframe, output_path = run_extraction("fake.docx")

        self.assertEqual(status, "提取完成")
        self.assertEqual(list(dataframe.columns), ["项目名称", "结果", "单位"])
        self.assertEqual(dataframe.iloc[0].to_dict(), {"项目名称": "白蛋白", "结果": "42.1", "单位": "g/L"})
        self.assertTrue(str(output_path).endswith(".xlsx"))


if __name__ == "__main__":
    unittest.main()
