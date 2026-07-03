import shutil
import re
from pathlib import Path

from lab_report_extractor import export_rows_to_xlsx, extract_lab_items_from_file
from medical_output_flow import DEFAULT_PATIENT_NAME, DEFAULT_STUDENT_ID, ensure_patient_output_dir


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "outputs"
LAB_RESULT_STEM = "lab_extract_result"


def build_field_artifact_stem(field_name, fallback=LAB_RESULT_STEM):
    text = str(field_name or "").strip()
    if not text:
        return fallback
    text = re.sub(r"[：:、，,（）()\[\]{}]+", "_", text)
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or fallback


def build_saved_source_path(submission_dir, source_path, field_name=None):
    source = Path(source_path)
    stem = build_field_artifact_stem(field_name, fallback=source.stem)
    return Path(submission_dir) / f"{stem}{source.suffix}"


def run_report_upload_flow(
    file_path,
    output_dir=OUTPUT_DIR,
    patient_name=DEFAULT_PATIENT_NAME,
    patient_output_dir=None,
    student_id=DEFAULT_STUDENT_ID,
    field_name=None,
):
    status, output_path, _ = run_report_upload_flow_with_rows(
        file_path,
        output_dir=output_dir,
        patient_name=patient_name,
        patient_output_dir=patient_output_dir,
        student_id=student_id,
        field_name=field_name,
    )
    return status, output_path


def save_report_file_only(
    file_path,
    output_dir=OUTPUT_DIR,
    patient_name=DEFAULT_PATIENT_NAME,
    patient_output_dir=None,
    student_id=DEFAULT_STUDENT_ID,
    field_name=None,
):
    if not file_path:
        return "请先上传文件。", None

    source_path = Path(file_path)
    submission_dir = ensure_patient_output_dir(
        output_dir=output_dir,
        patient_name=patient_name,
        patient_output_dir=patient_output_dir,
        student_id=student_id,
    )

    saved_source_path = build_saved_source_path(submission_dir, source_path, field_name=field_name)
    shutil.copy2(source_path, saved_source_path)
    return "上传完成", str(saved_source_path)


def run_report_upload_flow_with_rows(
    file_path,
    output_dir=OUTPUT_DIR,
    patient_name=DEFAULT_PATIENT_NAME,
    patient_output_dir=None,
    student_id=DEFAULT_STUDENT_ID,
    field_name=None,
):
    if not file_path:
        return "请先上传文件。", None

    source_path = Path(file_path)
    submission_dir = ensure_patient_output_dir(
        output_dir=output_dir,
        patient_name=patient_name,
        patient_output_dir=patient_output_dir,
        student_id=student_id,
    )

    saved_source_path = build_saved_source_path(submission_dir, source_path, field_name=field_name)
    shutil.copy2(source_path, saved_source_path)

    try:
        rows = extract_lab_items_from_file(str(saved_source_path))
    except Exception as exc:
        return f"提取失败：{exc}", None, []

    result_stem = f"{build_field_artifact_stem(field_name)}_提取结果" if field_name else LAB_RESULT_STEM
    output_path = export_rows_to_xlsx(rows, submission_dir, result_stem)
    return "提取完成", str(output_path), rows
