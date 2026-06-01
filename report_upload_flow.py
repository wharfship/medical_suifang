import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from lab_report_extractor import export_rows_to_xlsx, extract_lab_items_from_file
from medical_output_flow import ensure_session_output_dir


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "outputs"


def build_output_stem():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = uuid4().hex[:8]
    return f"{timestamp}_{suffix}_lab_extract_result"


def build_output_folder_name():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = uuid4().hex[:8]
    return f"{timestamp}_{suffix}"


def run_report_upload_flow(file_path, output_dir=OUTPUT_DIR, session_output_dir=None):
    if not file_path:
        return "请先上传文件。", None

    source_path = Path(file_path)
    submission_dir = ensure_session_output_dir(output_dir=output_dir, session_output_dir=session_output_dir)

    saved_source_path = submission_dir / source_path.name
    shutil.copy2(source_path, saved_source_path)

    try:
        rows = extract_lab_items_from_file(str(saved_source_path))
    except Exception as exc:
        return f"提取失败：{exc}", None

    output_path = export_rows_to_xlsx(rows, submission_dir, build_output_stem())
    return "提取完成", str(output_path)
