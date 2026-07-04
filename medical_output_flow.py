import shutil
from datetime import date
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "outputs"
DEFAULT_PATIENT_NAME = "\u674e\u540c\u5b66"
DEFAULT_STUDENT_ID = ""


def sanitize_storage_fragment(value, fallback="patient"):
    text = str(value or "").strip()
    for char in '\\/:*?"<>|':
        text = text.replace(char, "_")
    text = "_".join(part for part in text.split() if part)
    return text or fallback


def build_patient_storage_name(patient_name=DEFAULT_PATIENT_NAME, student_id=DEFAULT_STUDENT_ID):
    normalized_patient_name = sanitize_storage_fragment(patient_name, fallback="patient")
    normalized_student_id = sanitize_storage_fragment(student_id, fallback="unknown")
    if normalized_student_id and normalized_student_id != "unknown":
        return f"{normalized_patient_name}_{normalized_student_id}"
    return normalized_patient_name


def build_followup_result_dirname(followup_date=None, followup_label=None):
    label_text = str(followup_label or "").strip()
    if label_text:
        return label_text
    target_date = followup_date or date.today()
    if isinstance(target_date, str):
        date_text = target_date.strip()
    else:
        date_text = target_date.strftime("%Y.%m.%d")
    return f"{date_text}随访结果"


def ensure_patient_output_dir(
    output_dir=OUTPUT_DIR,
    patient_name=DEFAULT_PATIENT_NAME,
    patient_output_dir=None,
    student_id=DEFAULT_STUDENT_ID,
    followup_date=None,
    followup_label=None,
):
    if patient_output_dir:
        target_dir = Path(patient_output_dir)
    else:
        patient_dir = Path(output_dir) / build_patient_storage_name(patient_name, student_id)
        target_dir = patient_dir / build_followup_result_dirname(followup_date, followup_label=followup_label)
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def persist_followup_export(
    source_excel_path,
    output_dir=OUTPUT_DIR,
    uploaded_report_path=None,
    patient_name=DEFAULT_PATIENT_NAME,
    patient_output_dir=None,
    student_id=DEFAULT_STUDENT_ID,
    followup_date=None,
    followup_label=None,
):
    source_excel = Path(source_excel_path)
    submission_dir = ensure_patient_output_dir(
        output_dir=output_dir,
        patient_name=patient_name,
        patient_output_dir=patient_output_dir,
        student_id=student_id,
        followup_date=followup_date,
        followup_label=followup_label,
    )

    target_excel_path = submission_dir / source_excel.name
    shutil.copy2(source_excel, target_excel_path)

    if uploaded_report_path:
        report_path = Path(uploaded_report_path)
        if report_path.exists():
            shutil.copy2(report_path, submission_dir / report_path.name)

    return str(target_excel_path)
