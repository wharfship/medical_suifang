import shutil
from pathlib import Path

from lab_report_extractor import export_rows_to_xlsx, extract_lab_items_from_file
from medical_output_flow import DEFAULT_PATIENT_NAME, ensure_patient_output_dir


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "outputs"
LAB_RESULT_STEM = "lab_extract_result"


def run_report_upload_flow(
    file_path,
    output_dir=OUTPUT_DIR,
    patient_name=DEFAULT_PATIENT_NAME,
    patient_output_dir=None,
):
    if not file_path:
        return "请先上传文件。", None

    source_path = Path(file_path)
    submission_dir = ensure_patient_output_dir(
        output_dir=output_dir,
        patient_name=patient_name,
        patient_output_dir=patient_output_dir,
    )

    saved_source_path = submission_dir / source_path.name
    shutil.copy2(source_path, saved_source_path)

    try:
        rows = extract_lab_items_from_file(str(saved_source_path))
    except Exception as exc:
        return f"提取失败：{exc}", None

    output_path = export_rows_to_xlsx(rows, submission_dir, LAB_RESULT_STEM)
    return "提取完成", str(output_path)
