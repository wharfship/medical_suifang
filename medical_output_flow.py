import shutil
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "outputs"
DEFAULT_PATIENT_NAME = "\u674e\u540c\u5b66"


def ensure_patient_output_dir(output_dir=OUTPUT_DIR, patient_name=DEFAULT_PATIENT_NAME, patient_output_dir=None):
    if patient_output_dir:
        target_dir = Path(patient_output_dir)
    else:
        target_dir = Path(output_dir) / patient_name
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def persist_followup_export(
    source_excel_path,
    output_dir=OUTPUT_DIR,
    uploaded_report_path=None,
    patient_name=DEFAULT_PATIENT_NAME,
    patient_output_dir=None,
):
    source_excel = Path(source_excel_path)
    submission_dir = ensure_patient_output_dir(
        output_dir=output_dir,
        patient_name=patient_name,
        patient_output_dir=patient_output_dir,
    )

    target_excel_path = submission_dir / source_excel.name
    shutil.copy2(source_excel, target_excel_path)

    if uploaded_report_path:
        report_path = Path(uploaded_report_path)
        if report_path.exists():
            shutil.copy2(report_path, submission_dir / report_path.name)

    return str(target_excel_path)
