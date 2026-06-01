import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "outputs"


def build_output_folder_name():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = uuid4().hex[:8]
    return f"{timestamp}_{suffix}"


def ensure_session_output_dir(output_dir=OUTPUT_DIR, session_output_dir=None):
    if session_output_dir:
        target_dir = Path(session_output_dir)
    else:
        target_dir = Path(output_dir) / build_output_folder_name()
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def persist_followup_export(
    source_excel_path,
    output_dir=OUTPUT_DIR,
    uploaded_report_path=None,
    session_output_dir=None,
):
    source_excel = Path(source_excel_path)
    submission_dir = ensure_session_output_dir(output_dir=output_dir, session_output_dir=session_output_dir)

    target_excel_path = submission_dir / source_excel.name
    shutil.copy2(source_excel, target_excel_path)

    if uploaded_report_path:
        report_path = Path(uploaded_report_path)
        if report_path.exists():
            shutil.copy2(report_path, submission_dir / report_path.name)

    return str(target_excel_path)
