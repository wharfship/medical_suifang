import os
import tempfile
import unittest
from unittest import mock

from medical_output_flow import (
    build_followup_result_dirname,
    build_patient_storage_name,
    ensure_patient_output_dir,
    persist_followup_export,
)

PATIENT_NAME = "\u674e\u540c\u5b66"
STUDENT_ID = "30291834"
FOLLOWUP_DATE = "2025.06.12"


class MedicalOutputPersistenceTests(unittest.TestCase):
    def test_build_followup_result_dirname_uses_readable_suffix(self):
        self.assertEqual(build_followup_result_dirname(FOLLOWUP_DATE), "2025.06.12随访结果")

    def test_persist_followup_export_saves_excel_and_uploaded_report_in_patient_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_excel_path = os.path.join(temp_dir, "medical_data.xlsx")
            uploaded_report_path = os.path.join(temp_dir, "report.pdf")
            output_dir = os.path.join(temp_dir, "outputs")
            patient_name = PATIENT_NAME

            with open(source_excel_path, "wb") as handle:
                handle.write(b"fake-excel")
            with open(uploaded_report_path, "wb") as handle:
                handle.write(b"fake-report")

            output_path = persist_followup_export(
                source_excel_path,
                output_dir=output_dir,
                uploaded_report_path=uploaded_report_path,
                patient_name=patient_name,
                student_id=STUDENT_ID,
                followup_date=FOLLOWUP_DATE,
            )

            submission_dir = os.path.dirname(output_path)
            copied_report_path = os.path.join(submission_dir, "report.pdf")
            expected_dir = os.path.join(
                output_dir,
                build_patient_storage_name(patient_name, STUDENT_ID),
                build_followup_result_dirname(FOLLOWUP_DATE),
            )

            self.assertTrue(os.path.exists(output_path))
            self.assertTrue(os.path.isdir(submission_dir))
            self.assertEqual(submission_dir, expected_dir)
            self.assertEqual(os.path.basename(output_path), "medical_data.xlsx")
            self.assertTrue(os.path.exists(copied_report_path))
            with open(copied_report_path, "rb") as handle:
                self.assertEqual(handle.read(), b"fake-report")

    def test_persist_followup_export_ignores_missing_uploaded_report_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_excel_path = os.path.join(temp_dir, "medical_data.xlsx")
            output_dir = os.path.join(temp_dir, "outputs")

            with open(source_excel_path, "wb") as handle:
                handle.write(b"fake-excel")

            output_path = persist_followup_export(
                source_excel_path,
                output_dir=output_dir,
                uploaded_report_path=os.path.join(temp_dir, "missing.xlsx"),
                patient_name=PATIENT_NAME,
                student_id=STUDENT_ID,
                followup_date=FOLLOWUP_DATE,
            )

            self.assertTrue(os.path.exists(output_path))
            self.assertEqual(len(os.listdir(os.path.dirname(output_path))), 1)

    def test_ensure_patient_output_dir_uses_patient_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = os.path.join(temp_dir, "outputs")

            patient_output_dir = ensure_patient_output_dir(
                output_dir=output_dir,
                patient_name=PATIENT_NAME,
                student_id=STUDENT_ID,
                followup_date=FOLLOWUP_DATE,
            )

            self.assertEqual(
                str(patient_output_dir),
                os.path.join(
                    output_dir,
                    build_patient_storage_name(PATIENT_NAME, STUDENT_ID),
                    build_followup_result_dirname(FOLLOWUP_DATE),
                ),
            )
            self.assertTrue(os.path.isdir(str(patient_output_dir)))

    def test_persist_followup_export_overwrites_existing_files_in_patient_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_excel_path = os.path.join(temp_dir, "medical_data.xlsx")
            uploaded_report_path = os.path.join(temp_dir, "report.pdf")
            output_dir = os.path.join(temp_dir, "outputs")
            patient_output_dir = os.path.join(
                output_dir,
                build_patient_storage_name(PATIENT_NAME, STUDENT_ID),
                build_followup_result_dirname(FOLLOWUP_DATE),
            )

            with open(source_excel_path, "wb") as handle:
                handle.write(b"first-excel")
            with open(uploaded_report_path, "wb") as handle:
                handle.write(b"first-report")

            first_output_path = persist_followup_export(
                source_excel_path,
                output_dir=output_dir,
                uploaded_report_path=uploaded_report_path,
                patient_name=PATIENT_NAME,
                student_id=STUDENT_ID,
                followup_date=FOLLOWUP_DATE,
            )

            with open(source_excel_path, "wb") as handle:
                handle.write(b"second-excel")
            with open(uploaded_report_path, "wb") as handle:
                handle.write(b"second-report")

            second_output_path = persist_followup_export(
                source_excel_path,
                output_dir=output_dir,
                uploaded_report_path=uploaded_report_path,
                patient_name=PATIENT_NAME,
                student_id=STUDENT_ID,
                followup_date=FOLLOWUP_DATE,
            )

            self.assertEqual(os.path.dirname(first_output_path), patient_output_dir)
            self.assertEqual(os.path.dirname(second_output_path), patient_output_dir)
            with open(second_output_path, "rb") as handle:
                self.assertEqual(handle.read(), b"second-excel")
            with open(os.path.join(patient_output_dir, "report.pdf"), "rb") as handle:
                self.assertEqual(handle.read(), b"second-report")


if __name__ == "__main__":
    unittest.main()
