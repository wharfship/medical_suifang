import os
import tempfile
import unittest

from medical_output_flow import build_output_folder_name, persist_followup_export


class MedicalOutputPersistenceTests(unittest.TestCase):
    def test_persist_followup_export_saves_excel_and_uploaded_report_in_unique_output_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_excel_path = os.path.join(temp_dir, "medical_data.xlsx")
            uploaded_report_path = os.path.join(temp_dir, "report.pdf")
            output_dir = os.path.join(temp_dir, "outputs")

            with open(source_excel_path, "wb") as handle:
                handle.write(b"fake-excel")
            with open(uploaded_report_path, "wb") as handle:
                handle.write(b"fake-report")

            output_path = persist_followup_export(
                source_excel_path,
                output_dir=output_dir,
                uploaded_report_path=uploaded_report_path,
            )

            submission_dir = os.path.dirname(output_path)
            copied_report_path = os.path.join(submission_dir, "report.pdf")

            self.assertTrue(os.path.exists(output_path))
            self.assertTrue(os.path.isdir(submission_dir))
            self.assertTrue(str(output_path).startswith(output_dir))
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
            )

            self.assertTrue(os.path.exists(output_path))
            self.assertEqual(len(os.listdir(os.path.dirname(output_path))), 1)

    def test_build_output_folder_name_returns_unique_folder_name(self):
        first_folder_name = build_output_folder_name()
        second_folder_name = build_output_folder_name()

        self.assertNotEqual(first_folder_name, second_folder_name)

    def test_persist_followup_export_reuses_given_session_output_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_excel_path = os.path.join(temp_dir, "medical_data.xlsx")
            session_output_dir = os.path.join(temp_dir, "outputs", "session-001")

            with open(source_excel_path, "wb") as handle:
                handle.write(b"fake-excel")

            first_output_path = persist_followup_export(source_excel_path, session_output_dir=session_output_dir)
            second_output_path = persist_followup_export(source_excel_path, session_output_dir=session_output_dir)

            self.assertEqual(os.path.dirname(first_output_path), session_output_dir)
            self.assertEqual(os.path.dirname(second_output_path), session_output_dir)


if __name__ == "__main__":
    unittest.main()
