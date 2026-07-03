import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import pandas as pd

from extract_demo import run_extraction
from lab_report_extractor import (
    DISPLAY_COLUMNS,
    EXTRACTION_PROMPT,
    build_display_rows,
    extract_followup_value_from_rows,
    export_rows_to_xlsx,
    extract_first_image_payload,
    extract_lab_items_from_file,
    normalize_extracted_items,
    parse_model_response,
)
from medical_output_flow import build_followup_result_dirname, build_patient_storage_name
from report_upload_flow import build_field_artifact_stem, run_report_upload_flow, save_report_file_only

PATIENT_NAME = "\u674e\u540c\u5b66"
STUDENT_ID = "30291834"


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
                "item_name": "ALP",
                "abbr": "ALP",
                "result": "103",
                "unit": "U/L",
                "reference_range": "50-135",
            },
            {
                "item_name": "ALP",
                "abbr": "ALP",
                "result": "103",
                "unit": "U/L",
                "reference_range": "50-135",
            },
            {
                "item_name": "ALB",
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
                    "item_name": "ALP",
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
                "item_name": "Albumin",
                "abbr": "ALB",
                "result": "42.1",
                "unit": "g/L",
                "reference_range": "40.0-55.0",
            }
        ]

        display_rows = build_display_rows(rows)

        self.assertEqual(
            display_rows,
            [{DISPLAY_COLUMNS[0]: "Albumin", DISPLAY_COLUMNS[1]: "42.1", DISPLAY_COLUMNS[2]: "g/L"}],
        )


class FollowupValueExtractionTests(unittest.TestCase):
    def test_extracts_creatinine_value_by_item_name(self):
        rows = [
            {
                "item_name": "肌酐（酶法）",
                "abbr": "CREA",
                "result": "66",
                "unit": "umol/L",
                "reference_range": "41-81",
            }
        ]

        value = extract_followup_value_from_rows("血生化：血清肌酐", rows)

        self.assertEqual(value, "66")

    def test_extracts_creatinine_value_when_item_name_has_prefix_and_abbr_is_cr(self):
        rows = [
            {
                "item_name": "*肌酐（酶法）",
                "abbr": "Cr",
                "result": "117.8",
                "unit": "umol/L",
                "reference_range": "41.0-111.0",
            }
        ]

        value = extract_followup_value_from_rows("血生化：血清肌酐", rows)

        self.assertEqual(value, "117.8")

    def test_extracts_creatinine_value_by_abbr_when_item_name_is_unstable(self):
        rows = [
            {
                "item_name": "项目7",
                "abbr": "CREA",
                "result": "88",
                "unit": "umol/L",
                "reference_range": "41.0-111.0",
            }
        ]

        value = extract_followup_value_from_rows("血生化：血清肌酐", rows)

        self.assertEqual(value, "88")

    def test_extracts_urine_summary_by_item_names(self):
        rows = [
            {
                "item_name": "潜血",
                "abbr": "BLD",
                "result": "Trace-Lysed",
                "unit": "",
                "reference_range": "-",
            },
            {
                "item_name": "蛋白质",
                "abbr": "PRO",
                "result": "Trace",
                "unit": "g/L",
                "reference_range": "-",
            },
        ]

        value = extract_followup_value_from_rows("尿常规：尿蛋白、尿潜血", rows)

        self.assertEqual(value, "尿潜血：Trace-Lysed；尿蛋白：Trace")

    def test_extracts_urine_summary_by_abbr_when_item_names_are_unstable(self):
        rows = [
            {
                "item_name": "项目15",
                "abbr": "BLD",
                "result": "Trace-Lysed",
                "unit": "",
                "reference_range": "-",
            },
            {
                "item_name": "项目16",
                "abbr": "PRO",
                "result": "Trace",
                "unit": "g/L",
                "reference_range": "-",
            },
        ]

        value = extract_followup_value_from_rows("尿常规：尿蛋白、尿潜血", rows)

        self.assertEqual(value, "尿潜血：Trace-Lysed；尿蛋白：Trace")

    def test_extracts_urine_summary_by_common_item_aliases(self):
        rows = [
            {
                "item_name": "尿潜血",
                "abbr": "BLD",
                "result": "阴性",
                "unit": "",
                "reference_range": "-",
            },
            {
                "item_name": "蛋白",
                "abbr": "PRO",
                "result": "Trace",
                "unit": "g/L",
                "reference_range": "-",
            },
        ]

        value = extract_followup_value_from_rows("尿常规：尿蛋白、尿潜血", rows)

        self.assertEqual(value, "尿潜血：阴性；尿蛋白：Trace")


class ExportRowsToXlsxTests(unittest.TestCase):
    def test_export_writes_projected_columns(self):
        rows = [
            {
                "item_name": "Creatinine",
                "abbr": "Cr",
                "result": "50.4",
                "unit": "umol/L",
                "reference_range": "41.0-111.0",
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = export_rows_to_xlsx(rows, temp_dir, "sample")
            dataframe = pd.read_excel(output_path)

        self.assertEqual(list(dataframe.columns), DISPLAY_COLUMNS)
        self.assertEqual(
            dataframe.iloc[0].to_dict(),
            {DISPLAY_COLUMNS[0]: "Creatinine", DISPLAY_COLUMNS[1]: 50.4, DISPLAY_COLUMNS[2]: "umol/L"},
        )


class DocxImageExtractionTests(unittest.TestCase):
    def test_extract_first_image_payload_rejects_docx_without_media(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            docx_path = os.path.join(temp_dir, "empty.docx")
            with zipfile.ZipFile(docx_path, "w") as archive:
                archive.writestr("[Content_Types].xml", "")

            with self.assertRaisesRegex(ValueError, "图片"):
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
{"items":[{"item_name":"Creatinine","abbr":"Cr","result":"50.4","unit":"umol/L","reference_range":"41.0-111.0"}]}
```"""

        rows = parse_model_response(content)

        self.assertEqual(
            rows,
            [
                {
                    "item_name": "Creatinine",
                    "abbr": "Cr",
                    "result": "50.4",
                    "unit": "umol/L",
                    "reference_range": "41.0-111.0",
                }
            ],
        )


class PromptContractTests(unittest.TestCase):
    def test_extraction_prompt_requires_full_image_and_lower_half_rows(self):
        self.assertIn("entire image", EXTRACTION_PROMPT)
        self.assertIn("top to bottom", EXTRACTION_PROMPT)
        self.assertIn("do not stop after the first section", EXTRACTION_PROMPT)
        self.assertIn("lower half of the image", EXTRACTION_PROMPT)


class ExtractionFlowTests(unittest.TestCase):
    def test_extract_lab_items_retries_when_result_matches_abbreviation(self):
        first_pass = """{"items":[{"item_name":"ALP","abbr":"ALP","result":"ALP","unit":"U/L","reference_range":"50-135"}]}"""
        second_pass = """{"items":[{"item_name":"ALP","abbr":"ALP","result":"103","unit":"U/L","reference_range":"50-135"}]}"""
        client = FakeClient([first_pass, second_pass])

        with patch(
            "lab_report_extractor.extract_first_image_payload",
            return_value="data:image/png;base64,abc",
        ):
            rows = extract_lab_items_from_file("fake.docx", client=client)

        self.assertEqual(rows[0]["result"], "103")
        self.assertEqual(len(client.calls), 2)

    def test_extract_lab_items_retries_when_result_matches_unit(self):
        first_pass = """{"items":[{"item_name":"ALB","abbr":"ALB","result":"g/L","unit":"g/L","reference_range":"40.0-55.0"}]}"""
        second_pass = """{"items":[{"item_name":"ALB","abbr":"ALB","result":"42.1","unit":"g/L","reference_range":"40.0-55.0"}]}"""
        client = FakeClient([first_pass, second_pass])

        with patch(
            "lab_report_extractor.extract_first_image_payload",
            return_value="data:image/png;base64,abc",
        ):
            rows = extract_lab_items_from_file("fake.docx", client=client)

        self.assertEqual(rows[0]["result"], "42.1")
        self.assertEqual(len(client.calls), 2)

    def test_extract_lab_items_merges_bottom_crop_when_urine_chemistry_is_missing(self):
        full_pass = """{"items":[
            {"item_name":"红细胞","abbr":"RBC","result":"7","unit":"/uL","reference_range":"0-17"},
            {"item_name":"白细胞","abbr":"WBC","result":"4","unit":"/uL","reference_range":"0-28"},
            {"item_name":"粘液丝","abbr":"MUCS","result":"24","unit":"/uL","reference_range":"0-28"}
        ]}"""
        bottom_pass = """{"items":[
            {"item_name":"潜血","abbr":"BLD","result":"Trace-Lysed","unit":"","reference_range":"-"},
            {"item_name":"蛋白质","abbr":"PRO","result":"Trace","unit":"g/L","reference_range":"-"},
            {"item_name":"比重","abbr":"SG","result":"1.023","unit":"","reference_range":"1.003-1.030"}
        ]}"""
        client = FakeClient([full_pass, bottom_pass])

        with patch(
            "lab_report_extractor.extract_first_image_payload",
            return_value="data:image/png;base64,full",
        ), patch(
            "lab_report_extractor.extract_bottom_crop_payload",
            return_value="data:image/png;base64,bottom",
        ):
            rows = extract_lab_items_from_file("fake.png", client=client)

        self.assertEqual(len(client.calls), 2)
        self.assertIn("BLD", {row["abbr"] for row in rows})
        self.assertIn("PRO", {row["abbr"] for row in rows})
        self.assertEqual(client.calls[1]["messages"][0]["content"][1]["image_url"]["url"], "data:image/png;base64,bottom")


class ExtractDemoTests(unittest.TestCase):
    def test_run_extraction_returns_download_path_only(self):
        full_rows = [
            {
                "item_name": "Albumin",
                "abbr": "ALB",
                "result": "42.1",
                "unit": "g/L",
                "reference_range": "40.0-55.0",
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = os.path.join(temp_dir, "fake.docx")
            with open(source_path, "wb") as handle:
                handle.write(b"fake-docx")

            with patch("report_upload_flow.extract_lab_items_from_file", return_value=full_rows):
                status, output_path = run_extraction(source_path)

        self.assertEqual(status, "提取完成")
        self.assertTrue(str(output_path).endswith(".xlsx"))

    def test_run_extraction_returns_error_message_for_invalid_docx(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            docx_path = os.path.join(temp_dir, "broken.docx")
            with open(docx_path, "wb") as handle:
                handle.write(b"not a zip payload")

            status, output_path = run_extraction(docx_path)

        self.assertIn("docx", status.lower())
        self.assertIsNone(output_path)


class ExtractDemoOutputPersistenceTests(unittest.TestCase):
    def test_build_field_artifact_stem_normalizes_followup_field_name(self):
        self.assertEqual(build_field_artifact_stem("血生化：血清肌酐"), "血生化_血清肌酐")
        self.assertEqual(build_field_artifact_stem("尿常规：尿蛋白、尿潜血"), "尿常规_尿蛋白_尿潜血")

    def test_run_report_upload_flow_saves_excel_and_original_file_in_patient_folder(self):
        full_rows = [
            {
                "item_name": "Albumin",
                "abbr": "ALB",
                "result": "42.1",
                "unit": "g/L",
                "reference_range": "40.0-55.0",
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = os.path.join(temp_dir, "outputs")
            source_path = os.path.join(temp_dir, "input.jpg")
            patient_name = PATIENT_NAME
            with open(source_path, "wb") as handle:
                handle.write(b"fake-image")

            with patch("report_upload_flow.extract_lab_items_from_file", return_value=full_rows):
                status, output_path = run_report_upload_flow(
                    source_path,
                    output_dir=output_dir,
                    patient_name=patient_name,
                    student_id=STUDENT_ID,
                    field_name="血生化：血清肌酐",
                )

            self.assertTrue(os.path.exists(output_path))
            submission_dir = os.path.dirname(output_path)
            copied_input_path = os.path.join(submission_dir, "血生化_血清肌酐.jpg")
            self.assertTrue(os.path.isdir(submission_dir))
            self.assertEqual(
                submission_dir,
                os.path.join(
                    output_dir,
                    build_patient_storage_name(patient_name, STUDENT_ID),
                    build_followup_result_dirname(),
                ),
            )
            self.assertTrue(os.path.exists(copied_input_path))
            self.assertEqual(os.path.basename(output_path), "血生化_血清肌酐_提取结果.xlsx")
            with open(copied_input_path, "rb") as handle:
                self.assertEqual(handle.read(), b"fake-image")

        self.assertTrue(status)
        self.assertTrue(str(output_path).endswith(".xlsx"))

    def test_run_report_upload_flow_overwrites_existing_files_in_patient_folder(self):
        full_rows = [
            {
                "item_name": "Albumin",
                "abbr": "ALB",
                "result": "42.1",
                "unit": "g/L",
                "reference_range": "40.0-55.0",
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = os.path.join(temp_dir, "outputs")
            source_path = os.path.join(temp_dir, "input.jpg")
            with open(source_path, "wb") as handle:
                handle.write(b"fake-image-1")

            with patch("report_upload_flow.extract_lab_items_from_file", return_value=full_rows):
                _, first_output_path = run_report_upload_flow(
                    source_path,
                    output_dir=output_dir,
                    patient_name=PATIENT_NAME,
                    student_id=STUDENT_ID,
                )

            with open(source_path, "wb") as handle:
                handle.write(b"fake-image-2")

            with patch("report_upload_flow.extract_lab_items_from_file", return_value=full_rows):
                _, second_output_path = run_report_upload_flow(
                    source_path,
                    output_dir=output_dir,
                    patient_name=PATIENT_NAME,
                    student_id=STUDENT_ID,
                )

            self.assertEqual(os.path.dirname(first_output_path), os.path.dirname(second_output_path))
            self.assertEqual(first_output_path, second_output_path)
            patient_dir = os.path.dirname(second_output_path)
            with open(os.path.join(patient_dir, "input.jpg"), "rb") as handle:
                self.assertEqual(handle.read(), b"fake-image-2")

    def test_run_report_upload_flow_reuses_given_patient_output_dir(self):
        full_rows = [
            {
                "item_name": "Albumin",
                "abbr": "ALB",
                "result": "42.1",
                "unit": "g/L",
                "reference_range": "40.0-55.0",
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = os.path.join(temp_dir, "outputs")
            patient_output_dir = os.path.join(
                output_dir,
                build_patient_storage_name(PATIENT_NAME, STUDENT_ID),
                build_followup_result_dirname(),
            )
            source_path = os.path.join(temp_dir, "input.jpg")
            with open(source_path, "wb") as handle:
                handle.write(b"fake-image")

            with patch("report_upload_flow.extract_lab_items_from_file", return_value=full_rows):
                _, output_path = run_report_upload_flow(
                    source_path,
                    output_dir=output_dir,
                    patient_output_dir=patient_output_dir,
                )

        self.assertEqual(os.path.dirname(output_path), patient_output_dir)

    def test_save_report_file_only_copies_original_file_without_generating_excel(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = os.path.join(temp_dir, "outputs")
            source_path = os.path.join(temp_dir, "ultrasound.jpg")
            with open(source_path, "wb") as handle:
                handle.write(b"kidney-ultrasound")

            status, saved_path = save_report_file_only(
                source_path,
                output_dir=output_dir,
                patient_name=PATIENT_NAME,
                student_id=STUDENT_ID,
                field_name="肾脏彩超",
            )

            self.assertEqual(status, "上传完成")
            self.assertTrue(os.path.exists(saved_path))
            self.assertEqual(
                os.path.dirname(saved_path),
                os.path.join(
                    output_dir,
                    build_patient_storage_name(PATIENT_NAME, STUDENT_ID),
                    build_followup_result_dirname(),
                ),
            )
            self.assertEqual(os.path.basename(saved_path), "肾脏彩超.jpg")
            self.assertFalse(
                os.path.exists(
                    os.path.join(
                        output_dir,
                        build_patient_storage_name(PATIENT_NAME, STUDENT_ID),
                        build_followup_result_dirname(),
                        "lab_extract_result.xlsx",
                    )
                )
            )


if __name__ == "__main__":
    unittest.main()
