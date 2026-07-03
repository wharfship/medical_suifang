from Model_initialization import *
import gradio as gr
import html
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from excel_adjusting import *
from field_rules import (
    apply_field_completion_rules,
)
from lab_report_extractor import extract_followup_value_from_rows
from medical_output_flow import DEFAULT_PATIENT_NAME, OUTPUT_DIR, build_patient_storage_name, persist_followup_export
from report_upload_flow import run_report_upload_flow_with_rows, save_report_file_only
from workflow_status import (
    finalize_after_attempt_limit,
    get_field_attempt_limit,
    is_final_status,
    normalize_parse_result,
)

FILE_NAME = "子问题.xls"
FOLLOWUP_DATE = ""
BASE_DIR = Path(__file__).resolve().parent
excel_path = BASE_DIR / FILE_NAME
if not excel_path.exists():
    raise FileNotFoundError(f"Excel template not found: {excel_path}")
metadata = load_excel_template(excel_path)
tracker = FieldStateTracker(metadata)
field_attempts = {}
chat_history = []   # 专门给 gradio 的 Chatbot 用的
last_report_output_path = ""
PATIENT_NAME = DEFAULT_PATIENT_NAME
ACTIVE_STUDENT_ID = ""
ACTIVE_FOLLOWUP_DATE = ""
CURRENT_WORKING_DIR = BASE_DIR
SESSION_WORK_ROOT = OUTPUT_DIR / "_sessions"
SESSION_LOCK = threading.RLock()
SESSION_SCOPED_RUNTIME = False

ALLOWED_REPORT_SUFFIXES = {".docx", ".png", ".jpg", ".jpeg"}
ALLOWED_REPORT_FILE_TYPES = [".docx", ".png", ".jpg", ".jpeg"]
UPLOAD_TRIGGER_KEYWORDS = ("化验", "检查", "血生化", "肌酐", "尿常规", "肾脏", "报告")
UPLOAD_REVEAL_REMAINING_FIELDS = 6
UPLOAD_REVEAL_PROGRESS = 0.72
TARGETED_UPLOAD_FIELDS = {
    "随访时受者状态",
    "血生化：血清肌酐",
    "尿常规：尿蛋白、尿潜血",
    "肾脏彩超",
}
DEFAULT_INPUT_PLACEHOLDER = "请直接输入您的回答，如不清楚也可以说“不知道”"
TARGETED_UPLOAD_PLACEHOLDER = "这题可以直接说，也可以上传化验单照片"
KIDNEY_ULTRASOUND_FIELD = "肾脏彩超"
COMPUTED_SUMMARY_FIELDS = {
    "（若有高血压）药物控制方案": [
        ("药物使用情况", "（若有高血压）药物使用情况"),
        ("目前控制情况", "（若有高血压）目前控制情况"),
    ],
    "（若有糖尿病）药物控制方案": [
        ("药物使用情况", "（若有糖尿病）药物使用情况"),
        ("胰岛素使用情况", "（若有糖尿病）胰岛素使用情况"),
        ("目前控制情况", "（若有糖尿病）目前控制情况"),
    ],
    "（若曾患冠心病）治疗方式": [
        ("药物使用情况", "（若曾患冠心病）药物使用情况"),
        ("手术情况", "（若曾患冠心病）手术情况"),
        ("目前控制情况", "（若曾患冠心病）目前控制情况"),
    ],
    "（若曾患脑血管病）具体疾病、治疗方式及有无后遗症": [
        ("患病类型", "（若曾患脑血管病）患病类型"),
        ("药物使用情况", "（若曾患脑血管病）药物使用情况"),
        ("手术情况", "（若曾患脑血管病）手术情况"),
        ("后遗症情况", "（若曾患脑血管病）后遗症情况"),
        ("目前控制情况", "（若曾患脑血管病）目前控制情况"),
    ],
    "（若有其余病史）请描述具体疾病、治疗方式、用药种类、用法、治疗效果": [
        ("具体疾病名称", "（若有其余病史）具体疾病名称"),
        ("药物使用情况", "（若有其余病史）药物使用情况"),
        ("手术情况", "（若有其余病史）手术情况"),
        ("目前控制情况", "（若有其余病史）目前控制情况"),
    ],
}


def normalize_patient_name(patient_name):
    text = str(patient_name or "").strip()
    return text or DEFAULT_PATIENT_NAME


def sanitize_path_fragment(value, fallback="session"):
    text = re.sub(r'[\\/:*?"<>|]+', "_", str(value or "").strip())
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"_+", "_", text).strip("._")
    return text or fallback


def create_session_working_dir(patient_name, student_id=""):
    SESSION_WORK_ROOT.mkdir(parents=True, exist_ok=True)
    safe_name = sanitize_path_fragment(build_patient_storage_name(patient_name, student_id), fallback="patient")
    session_id = uuid.uuid4().hex[:8]
    session_dir = SESSION_WORK_ROOT / f"{safe_name}_{session_id}"
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def build_session_state(patient_name=None, student_id=""):
    normalized_name = normalize_patient_name(patient_name)
    session_metadata = load_excel_template(excel_path)
    normalized_student_id = str(student_id or "").strip()
    working_dir = create_session_working_dir(normalized_name, normalized_student_id)
    return {
        "patient_name": normalized_name,
        "student_id": normalized_student_id,
        "followup_date": "",
        "metadata": session_metadata,
        "tracker": FieldStateTracker(session_metadata),
        "field_attempts": {},
        "chat_history": [],
        "last_report_output_path": "",
        "working_dir": str(working_dir),
    }


def apply_session_state(session_state=None, patient_name=None, session_scoped=False):
    global tracker, metadata, field_attempts, chat_history, last_report_output_path, PATIENT_NAME, ACTIVE_STUDENT_ID, ACTIVE_FOLLOWUP_DATE, CURRENT_WORKING_DIR, SESSION_SCOPED_RUNTIME

    active_state = session_state or build_session_state(patient_name)
    active_state["patient_name"] = normalize_patient_name(patient_name or active_state.get("patient_name"))
    active_state["student_id"] = str(active_state.get("student_id") or "").strip()
    active_state["followup_date"] = str(active_state.get("followup_date") or "").strip()
    active_state["metadata"] = active_state.get("metadata") or load_excel_template(excel_path)
    active_state["tracker"] = active_state.get("tracker") or FieldStateTracker(active_state["metadata"])
    active_state["field_attempts"] = active_state.get("field_attempts") or {}
    active_state["chat_history"] = clone_chat_history(active_state.get("chat_history"))
    active_state["last_report_output_path"] = str(active_state.get("last_report_output_path") or "")
    SESSION_SCOPED_RUNTIME = bool(session_scoped)

    if SESSION_SCOPED_RUNTIME:
        working_dir = Path(active_state.get("working_dir") or create_session_working_dir(active_state["patient_name"], active_state["student_id"]))
        working_dir.mkdir(parents=True, exist_ok=True)
        active_state["working_dir"] = str(working_dir)
    else:
        working_dir = BASE_DIR
        active_state["working_dir"] = str(working_dir)

    metadata = active_state["metadata"]
    tracker = active_state["tracker"]
    field_attempts = active_state["field_attempts"]
    chat_history = active_state["chat_history"]
    last_report_output_path = active_state["last_report_output_path"]
    PATIENT_NAME = active_state["patient_name"]
    ACTIVE_STUDENT_ID = active_state["student_id"]
    ACTIVE_FOLLOWUP_DATE = active_state["followup_date"]
    CURRENT_WORKING_DIR = working_dir
    return active_state


def snapshot_session_state():
    return {
        "patient_name": PATIENT_NAME,
        "student_id": ACTIVE_STUDENT_ID,
        "followup_date": ACTIVE_FOLLOWUP_DATE,
        "metadata": metadata,
        "tracker": tracker,
        "field_attempts": field_attempts,
        "chat_history": clone_chat_history(chat_history),
        "last_report_output_path": last_report_output_path,
        "working_dir": str(CURRENT_WORKING_DIR),
    }


def get_runtime_excel_path():
    return CURRENT_WORKING_DIR / "medical_data.xlsx"


def get_active_student_id(session_state=None):
    if isinstance(session_state, dict):
        return str(session_state.get("student_id") or "").strip()
    return str(ACTIVE_STUDENT_ID or "").strip()


def get_active_followup_date(session_state=None):
    if isinstance(session_state, dict):
        return str(session_state.get("followup_date") or "").strip()
    return str(ACTIVE_FOLLOWUP_DATE or "").strip()


def get_session_patient_output_dir():
    if not SESSION_SCOPED_RUNTIME or CURRENT_WORKING_DIR == BASE_DIR:
        return None
    return CURRENT_WORKING_DIR


def normalize_patient_name_input(patient_name):
    normalized_name = str(patient_name or "").replace("\u3000", " ").strip()
    normalized_name = re.sub(r"\s+", " ", normalized_name)
    return gr.update(value=normalized_name[:20])


def validate_patient_name(patient_name):
    normalized_name = str(patient_name or "").replace("\u3000", " ").strip()
    normalized_name = re.sub(r"\s+", " ", normalized_name)
    if not normalized_name:
        return False, "", "请输入患者姓名。"
    if len(normalized_name) < 2 or len(normalized_name) > 20:
        return False, normalized_name, "姓名长度需为2到20个字符。"
    if normalized_name.isdigit():
        return False, normalized_name, "姓名不能为纯数字。"
    if not re.fullmatch(r"[A-Za-z\u4e00-\u9fff· ]+", normalized_name):
        return False, normalized_name, "姓名格式不正确。"
    return True, normalized_name, ""


def validate_student_id(student_id):
    normalized_student_id = str(student_id or "").strip()
    if not normalized_student_id:
        return False, "", "请输入学工号。"
    if not normalized_student_id.isdigit() or len(normalized_student_id) != 8:
        return False, normalized_student_id, "学工号必须为8位数字。"
    return True, normalized_student_id, ""


def normalize_followup_date_input(followup_date):
    normalized_date = str(followup_date or "").strip()
    return gr.update(value=normalized_date)


def resolve_followup_date(followup_date):
    normalized_date = str(followup_date or "").strip()
    if normalized_date:
        return normalized_date
    configured_date = str(FOLLOWUP_DATE or "").strip()
    if configured_date:
        return configured_date
    return ""


def build_patient_context_html(patient_name="", student_id="", followup_date="", logged_in=False, message=""):
    if not logged_in:
        prompt = message or "请先填写患者姓名和学工号，然后点击“开始随访”。"
        return (
            "<div class='patient-context-card patient-context-pending'>"
            "<strong>请先登记患者信息</strong>"
            f"<span>{html.escape(prompt)}</span>"
            "</div>"
        )

    return (
        "<div class='patient-context-card'>"
        "<strong>当前患者</strong>"
        f"<span>{html.escape(patient_name)} | 学工号：{html.escape(student_id)} | 随访日期：{html.escape(followup_date or '当天')}</span>"
        "</div>"
    )


def build_login_required_view(session_state=None, patient_name="", student_id="", followup_date="", message="请先填写患者姓名和学工号，然后点击“开始随访”。"):
    active_state = session_state or build_session_state(patient_name or DEFAULT_PATIENT_NAME)
    active_state["patient_name"] = normalize_patient_name(patient_name or active_state.get("patient_name"))
    active_state["student_id"] = str(student_id or active_state.get("student_id") or "").strip()
    active_state["followup_date"] = resolve_followup_date(followup_date or active_state.get("followup_date"))
    return (
        active_state,
        message,
        [],
        "",
        build_patient_context_html(active_state["patient_name"], active_state["student_id"], active_state["followup_date"], logged_in=False, message=message),
        gr.update(value=build_progress_html(), visible=False),
        "",
        gr.update(value=None, visible=False),
        gr.update(value=pd.DataFrame(), visible=False),
        gr.update(interactive=False),
        gr.update(value="", visible=False),
        gr.update(value=None, visible=False),
        gr.update(value="", visible=False),
        gr.update(value="", visible=False),
        gr.update(value=None, visible=False),
        gr.update(
            value="",
            placeholder="请先填写患者姓名和学工号",
            interactive=False,
        ),
    )


def build_login_invalid_view(session_state=None, patient_name="", student_id="", followup_date="", message="请先填写患者姓名和学工号，然后点击“开始随访”。"):
    return build_login_required_view(session_state, patient_name, student_id, followup_date, message)


def normalize_student_id_input(student_id):
    normalized_student_id = re.sub(r"\D", "", str(student_id or "").strip())
    return gr.update(value=normalized_student_id[:8])


def start_followup(session_state, patient_name, student_id, followup_date):
    valid_patient_name, normalized_patient_name, patient_name_message = validate_patient_name(patient_name)
    valid_student_id, normalized_student_id, student_id_message = validate_student_id(student_id)
    resolved_followup_date = resolve_followup_date(followup_date)
    if not valid_patient_name:
        return build_login_invalid_view(session_state, normalized_patient_name, normalized_student_id, resolved_followup_date, patient_name_message)
    if not valid_student_id:
        return build_login_invalid_view(session_state, normalized_patient_name, normalized_student_id, resolved_followup_date, student_id_message)

    result = list(init_system(session_state, normalized_patient_name))
    result[0]["student_id"] = normalized_student_id
    result[0]["followup_date"] = resolved_followup_date
    result.insert(4, build_patient_context_html(normalized_patient_name, normalized_student_id, resolved_followup_date, logged_in=True))
    result[5] = gr.update(value=result[5], visible=True)
    result.insert(6, "")
    result[8] = gr.update(value=result[8], visible=False)
    result.insert(9, gr.update(interactive=True))
    result[15] = gr.update(value=result[15], interactive=True)
    return tuple(result)

CUSTOM_CSS = """
:root {
    --brand-ink: #15304f;
    --brand-subtle: #5a7189;
    --brand-line: rgba(117, 142, 168, 0.18);
    --brand-soft: #eef6ff;
    --brand-accent: #1b7bff;
    --brand-accent-dark: #1662d6;
    --surface: rgba(255, 255, 255, 0.92);
}

.gradio-container {
    background:
        radial-gradient(circle at top left, rgba(92, 180, 255, 0.22), transparent 26%),
        radial-gradient(circle at top right, rgba(35, 130, 255, 0.14), transparent 32%),
        linear-gradient(180deg, #f6f9ff 0%, #eef4fb 52%, #edf3f8 100%);
}

.app-shell {
    max-width: 1380px;
    margin: 0 auto;
    padding: 10px 0 14px;
}

.hero-card,
.sidebar-card,
.chat-card,
.data-card {
    border: 1px solid var(--brand-line);
    border-radius: 22px;
    background: var(--surface);
    box-shadow: 0 18px 45px rgba(44, 77, 117, 0.09);
    backdrop-filter: blur(12px);
}

.hero-card {
    padding: 24px 28px 18px;
    margin-bottom: 16px;
    overflow: hidden;
    position: relative;
}

.hero-card::after {
    content: "";
    position: absolute;
    right: -80px;
    top: -80px;
    width: 220px;
    height: 220px;
    border-radius: 999px;
    background: radial-gradient(circle, rgba(27, 123, 255, 0.14) 0%, rgba(27, 123, 255, 0) 70%);
    pointer-events: none;
}

.hero-grid {
    display: grid;
    grid-template-columns: minmax(0, 2.2fr) minmax(260px, 1fr);
    gap: 18px;
    align-items: stretch;
}

.hero-card h1 {
    margin: 0;
    font-size: 2.2rem;
    font-weight: 800;
    letter-spacing: -0.03em;
    color: var(--brand-ink);
}

.hero-card p {
    margin: 10px 0 12px;
    color: var(--brand-subtle);
    font-size: 1.02rem;
    line-height: 1.65;
}

.hero-badges {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 12px;
}

.hero-badges span {
    display: inline-flex;
    align-items: center;
    padding: 6px 12px;
    border-radius: 999px;
    background: #e9f3ff;
    color: #184a7c;
    font-size: 0.92rem;
    font-weight: 600;
}

.hero-stats {
    display: grid;
    gap: 12px;
}

.hero-stat {
    border-radius: 18px;
    padding: 14px 16px;
    background: linear-gradient(180deg, rgba(239, 247, 255, 0.95) 0%, rgba(230, 241, 252, 0.9) 100%);
    border: 1px solid rgba(169, 198, 230, 0.45);
}

.hero-stat strong {
    display: block;
    color: var(--brand-ink);
    font-size: 0.98rem;
    margin-bottom: 4px;
}

.hero-stat span {
    color: var(--brand-subtle);
    font-size: 0.92rem;
    line-height: 1.5;
}

.sidebar-card,
.chat-card,
.data-card {
    padding: 12px;
}

.sidebar-card {
    padding: 12px 12px 10px;
}

.workspace-row {
    align-items: start;
    gap: 14px;
}

.sidebar-stack {
    position: sticky;
    top: 16px;
}

.panel-subtitle {
    margin: 2px 0 8px;
    color: var(--brand-ink);
    font-size: 0.95rem;
    font-weight: 700;
}

.panel-note {
    margin: 0 0 8px;
    padding: 10px 12px;
    border-radius: 16px;
    background: #f5f9ff;
    color: var(--brand-subtle);
    font-size: 0.88rem;
    line-height: 1.5;
    border: 1px solid rgba(207, 227, 251, 0.9);
}

.patient-context-card {
    margin: 0 0 10px;
    padding: 12px 14px;
    border-radius: 16px;
    background: linear-gradient(180deg, rgba(238, 246, 255, 0.96) 0%, rgba(228, 240, 253, 0.96) 100%);
    border: 1px solid rgba(187, 210, 235, 0.95);
}

.patient-context-card strong {
    display: block;
    margin-bottom: 4px;
    color: var(--brand-ink);
    font-size: 0.94rem;
}

.patient-context-card span {
    color: var(--brand-subtle);
    font-size: 0.9rem;
    line-height: 1.55;
}

.patient-context-pending {
    background: linear-gradient(180deg, rgba(246, 249, 255, 0.98) 0%, rgba(240, 245, 252, 0.98) 100%);
}

.upload-stage-note {
    margin: 0 0 8px;
    padding: 10px 12px;
    border-radius: 16px;
    background: linear-gradient(180deg, rgba(247, 251, 255, 0.96) 0%, rgba(239, 246, 255, 0.96) 100%);
    border: 1px solid rgba(210, 227, 244, 0.95);
    color: var(--brand-subtle);
    font-size: 0.87rem;
    line-height: 1.55;
}

.upload-stage-note strong {
    display: block;
    margin-bottom: 4px;
    color: var(--brand-ink);
    font-size: 0.94rem;
}

.section-title {
    margin: 4px 0 12px;
    padding: 2px 6px;
    color: #193b5e;
    font-size: 1.04rem;
    font-weight: 700;
}

.compact-box textarea,
.compact-box input {
    border-radius: 16px !important;
}

.metric-box textarea,
.metric-box input {
    background: linear-gradient(180deg, #f9fbff 0%, #f1f7ff 100%) !important;
    border: 1px solid rgba(205, 222, 240, 0.95) !important;
    color: var(--brand-ink) !important;
    font-weight: 600;
}

.long-box textarea,
.long-box input {
    background: #fbfdff !important;
    border: 1px solid rgba(214, 228, 242, 0.95) !important;
    color: #47617b !important;
}

.button-row {
    gap: 10px;
    margin: 6px 0 10px;
}

.button-row > * {
    flex: 1 1 0;
}

.chat-head {
    margin: 2px 2px 10px;
    padding: 12px 14px;
    border-radius: 16px;
    background: linear-gradient(180deg, rgba(244, 249, 255, 0.96) 0%, rgba(237, 245, 255, 0.96) 100%);
    border: 1px solid rgba(208, 224, 241, 0.9);
    color: var(--brand-subtle);
    font-size: 0.94rem;
    line-height: 1.55;
}

.sidebar-primary {
    margin-bottom: 10px;
}

.compact-accordion {
    margin-top: 8px;
}

.progress-card {
    border-radius: 18px;
    padding: 14px 14px 12px;
    background: linear-gradient(180deg, rgba(246, 251, 255, 0.98) 0%, rgba(237, 245, 255, 0.96) 100%);
    border: 1px solid rgba(206, 225, 245, 0.95);
}

.progress-card strong {
    display: block;
    margin-bottom: 4px;
    color: var(--brand-ink);
    font-size: 1rem;
}

.progress-card span {
    display: block;
    color: var(--brand-subtle);
    font-size: 0.87rem;
    line-height: 1.5;
}

.progress-track {
    margin: 10px 0 8px;
    height: 10px;
    border-radius: 999px;
    background: rgba(184, 206, 231, 0.45);
    overflow: hidden;
}

.progress-fill {
    height: 100%;
    border-radius: 999px;
    background: linear-gradient(90deg, #4fa3ff 0%, #1b7bff 100%);
    box-shadow: 0 8px 18px rgba(27, 123, 255, 0.22);
    transition: width 0.3s ease;
}

.progress-meta {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    margin-top: 4px;
}

.progress-meta b {
    color: var(--brand-ink);
    font-size: 0.94rem;
}

.inline-upload-shell {
    margin-top: 10px;
    padding: 12px 14px;
    border-radius: 18px;
    background: linear-gradient(180deg, rgba(248, 251, 255, 0.96) 0%, rgba(239, 246, 255, 0.96) 100%);
    border: 1px solid rgba(207, 225, 245, 0.95);
}

.inline-upload-shell .panel-note {
    margin-bottom: 8px;
}

.chat-card .bubble-wrap,
.chat-card .message-wrap {
    font-size: 0.98rem;
}

.chat-card {
    min-height: 100%;
}

.chat-card .wrap {
    border-radius: 20px;
}

.composer-row {
    align-items: end;
    gap: 10px;
    margin-top: 8px;
}

.composer-row > :first-child {
    flex: 1 1 auto;
}

.composer-row > :last-child {
    min-width: 128px;
}

.chat-tip {
    margin: 8px 4px 2px;
    color: #6a8198;
    font-size: 0.88rem;
}

.chat-actions {
    margin-top: 0;
}

.primary-action button {
    background: linear-gradient(135deg, var(--brand-accent) 0%, var(--brand-accent-dark) 100%) !important;
    border: none !important;
    color: white !important;
    box-shadow: 0 14px 28px rgba(27, 123, 255, 0.28);
}

.soft-action button {
    background: #eef6ff !important;
    color: #184a7c !important;
    border: 1px solid #cfe3fb !important;
}

.upload-card {
    margin-bottom: 4px;
    padding: 4px 2px 6px;
    border-bottom: 1px dashed rgba(117, 142, 168, 0.28);
}

.data-shell {
    margin-top: 2px;
}

.data-card .gradio-dataframe {
    border-radius: 18px;
    overflow: hidden;
}

@media (max-width: 1080px) {
    .hero-grid {
        grid-template-columns: 1fr;
    }

    .sidebar-stack {
        position: static;
    }
}

@media (max-width: 780px) {
    .app-shell {
        padding: 12px 0 20px;
    }

    .hero-card,
    .sidebar-card,
    .chat-card,
    .data-card {
        border-radius: 18px;
    }

    .hero-card {
        padding: 18px 18px 14px;
    }

    .hero-card h1 {
        font-size: 1.72rem;
    }

    .button-row,
    .composer-row {
        flex-direction: column;
    }

    .composer-row > :last-child {
        min-width: 100%;
    }
}

#auto-report-download {
    display: none !important;
}
"""


AUTO_REPORT_DOWNLOAD_JS = """
() => {
    const button = document.querySelector('#auto-report-download button');
    if (button) {
        setTimeout(() => button.click(), 150);
    }
}
"""


COLUMN_NAMES = {
    "field": "填写内容",
    "value": "填写数据",
    "completion": "完整度",
    "status": "流程状态",
    "reasoning": "解释",
    "evidence": "数据原始依据",
}


def resolve_field_state(field, cache=None):
    if cache is None:
        cache = {}
    if field in cache:
        return cache[field]

    if field in tracker.filled_data:
        cache[field] = "completed"
        return cache[field]

    dependencies = metadata[field].get("依赖")
    if not dependencies:
        cache[field] = "pending"
        return cache[field]

    parent = dependencies.get("parent")
    if not parent or parent not in metadata:
        cache[field] = "pending"
        return cache[field]

    parent_state = resolve_field_state(parent, cache)
    if parent_state == "inactive":
        cache[field] = "inactive"
        return cache[field]

    if parent not in tracker.filled_data:
        cache[field] = "pending"
        return cache[field]

    parent_value = tracker.filled_data[parent].get("value")
    condition = dependencies.get("condition")
    opposite_condition = dependencies.get("opposite_condition")

    if condition is not None:
        allowed_values = condition if isinstance(condition, list) else [condition]
        cache[field] = "pending" if parent_value in allowed_values else "inactive"
        return cache[field]

    if opposite_condition is not None:
        blocked_values = opposite_condition if isinstance(opposite_condition, list) else [opposite_condition]
        cache[field] = "inactive" if parent_value in blocked_values else "pending"
        return cache[field]

    cache[field] = "pending"
    return cache[field]


def get_progress_state():
    state_cache = {}
    completed_count = 0
    inactive_count = 0

    for field in metadata:
        field_state = resolve_field_state(field, state_cache)
        if field_state == "completed":
            completed_count += 1
        elif field_state == "inactive":
            inactive_count += 1

    relevant_total = max(len(metadata) - inactive_count, 0)
    progress_percent = 100 if relevant_total == 0 else round((completed_count / relevant_total) * 100)

    return {
        "completed": completed_count,
        "inactive": inactive_count,
        "relevant_total": relevant_total,
        "percent": progress_percent,
    }


def build_progress_text():
    progress_state = get_progress_state()
    return f"{progress_state['completed']}/{progress_state['relevant_total']} ({progress_state['percent']}%)"


def build_progress_html():
    progress_state = get_progress_state()
    completed = progress_state["completed"]
    relevant_total = progress_state["relevant_total"]
    inactive = progress_state["inactive"]
    percent = progress_state["percent"]
    summary = f"已完成 {completed} 项"
    if relevant_total:
        summary += f" / 当前共需处理 {relevant_total} 项"

    inactive_hint = "当前没有自动跳过项"
    if inactive:
        inactive_hint = f"已自动跳过 {inactive} 项条件不满足的问题"

    return f"""
    <div class="progress-card">
        <strong>当前完成度 {percent}%</strong>
        <span>{html.escape(summary)}</span>
        <div class="progress-track">
            <div class="progress-fill" style="width: {percent}%;"></div>
        </div>
        <div class="progress-meta">
            <span>{html.escape(inactive_hint)}</span>
            <b>{completed}/{relevant_total or completed}</b>
        </div>
    </div>
    """


def should_reveal_upload_panel(current_field):
    progress_state = get_progress_state()
    relevant_total = progress_state["relevant_total"]
    if relevant_total == 0:
        return True

    completed_fields = progress_state["completed"]
    remaining_fields = max(relevant_total - completed_fields, 0)
    if current_field is None or remaining_fields <= UPLOAD_REVEAL_REMAINING_FIELDS:
        return True

    field_text = str(current_field or "")
    if any(keyword in field_text for keyword in UPLOAD_TRIGGER_KEYWORDS):
        return True

    return (completed_fields / relevant_total) >= UPLOAD_REVEAL_PROGRESS


def build_upload_stage_note(current_field):
    field_text = str(current_field or "")
    if current_field == KIDNEY_ULTRASOUND_FIELD:
        return (
            "<div class='upload-stage-note'>"
            "<strong>这题可上传肾脏彩超图片辅助填写</strong>"
            f"当前问题：{html.escape(field_text)}。如果手头有肾脏彩超图片，可以直接上传，系统会为您保存到当前患者目录。"
            "</div>"
        )

    if current_field in TARGETED_UPLOAD_FIELDS:
        return (
            "<div class='upload-stage-note'>"
            "<strong>这题可上传化验单辅助填写</strong>"
            f"当前问题：{html.escape(field_text)}。如果手头有化验单，可以直接上传照片或文档辅助填写当前题。"
            "</div>"
        )

    return (
        "<div class='upload-stage-note'>"
        "<strong>现在可以上传化验单</strong>"
        "已经进入化验或检查相关问题阶段，如手头有报告，现在上传会更顺手。"
        "</div>"
    )


def get_input_placeholder(current_field):
    if current_field == KIDNEY_ULTRASOUND_FIELD:
        return "这题可以直接说，也可以上传肾脏彩超图片"
    if current_field in TARGETED_UPLOAD_FIELDS:
        return TARGETED_UPLOAD_PLACEHOLDER
    return DEFAULT_INPUT_PLACEHOLDER


def build_upload_component_updates(current_field, clear_values=False):
    show_upload_panel = should_reveal_upload_panel(current_field)
    placeholder_update = gr.update(placeholder=get_input_placeholder(current_field))
    if clear_values:
        return (
            gr.update(value=build_upload_stage_note(current_field), visible=show_upload_panel),
            gr.update(visible=show_upload_panel, value=None),
            gr.update(visible=show_upload_panel, value=""),
            gr.update(visible=show_upload_panel, value=""),
            placeholder_update,
        )

    return (
        gr.update(value=build_upload_stage_note(current_field), visible=show_upload_panel),
        gr.update(visible=show_upload_panel, value=None),
        gr.update(visible=show_upload_panel, value=""),
        gr.update(visible=show_upload_panel, value=""),
        placeholder_update,
    )


def build_result_component_updates(file_path, df, current_field):
    followup_finished = current_field is None
    return (
        gr.update(value=file_path, visible=followup_finished),
        gr.update(value=df, visible=followup_finished),
    )


def export_tracker_data():
    df = pd.DataFrame(tracker.get_parse_history())
    df = filter_exported_child_rows(df)
    df = df.rename(columns=COLUMN_NAMES)
    excel_file = get_runtime_excel_path()
    df.to_excel(excel_file, index=False, engine="openpyxl")
    format_excel(excel_file, excel_file)
    return df, str(excel_file)


def add_assistant_message(message, current_chat_history):
    tracker.add_dialogue("AI", message)
    current_chat_history.append({"role": "assistant", "content": message})


def build_confirmation_message(field, result):
    value = result.get("field_value", "")
    confidence = result.get("confidence", 0.0)
    status = result.get("status")
    completion = result.get("completion")

    if status == "later":
        return "好的，这项我先记为待补充，您后续提供资料后再完善。"
    if status == "manual_review":
        return "这项信息我先标记为需人工复核，后续再处理。"
    if completion == "complete" and value:
        return f"已记录: {field} = {value} (置信度: {confidence:.2f})"
    if completion == "partial":
        if value:
            return f"已记录目前能确认的部分信息: {field} = {value}"
        return "这项我先按部分信息收口，后续如有资料可再补充。"
    return "好的，这项先记为暂未获取。"


def extract_numeric_value(text):
    if text is None:
        return None
    match = re.search(r"\d+(?:\.\d+)?", str(text))
    if not match:
        return None
    return float(match.group())


def build_bmi_result():
    height_cm = extract_numeric_value(tracker.get_field_value("当前身高"))
    weight_kg = extract_numeric_value(tracker.get_field_value("当前体重"))

    if not height_cm or not weight_kg:
        return {
            "status": "done",
            "completion": "empty",
            "field_value": "",
            "confidence": 1.0,
            "reasoning": "缺少可用的身高或体重，无法计算 BMI。",
            "evidence": "AI: BMI 由当前身高与当前体重自动计算；当前缺少至少一项有效数值。",
        }

    bmi_value = round(weight_kg / ((height_cm / 100) ** 2), 2)
    return {
        "status": "done",
        "completion": "complete",
        "field_value": str(bmi_value),
        "confidence": 1.0,
        "reasoning": "根据当前身高和当前体重自动计算 BMI。",
        "evidence": f"AI: BMI 由系统自动计算。 patient: 当前身高={height_cm}cm, 当前体重={weight_kg}kg。",
    }


def build_summary_field_result(field):
    parts = COMPUTED_SUMMARY_FIELDS.get(field, [])
    summary_value = "；".join(
        f"{label}：{tracker.get_field_value(child_field) or ''}"
        for label, child_field in parts
    )
    child_evidence = "\n".join(
        tracker.filled_data.get(child_field, {}).get("evidence", "")
        for _, child_field in parts
        if tracker.filled_data.get(child_field, {}).get("evidence", "")
    )
    return {
        "status": "done",
        "completion": "complete",
        "field_value": summary_value,
        "confidence": 1.0,
        "reasoning": f"根据已完成的子字段自动汇总 {field}。",
        "evidence": child_evidence,
    }


def filter_exported_child_rows(df):
    if df.empty or "field" not in df.columns:
        return df

    completed_fields = set(df["field"].tolist())
    hidden_child_fields = {
        child_field
        for parent_field, parts in COMPUTED_SUMMARY_FIELDS.items()
        if parent_field in completed_fields
        for _, child_field in parts
    }
    if not hidden_child_fields:
        return df

    return df[~df["field"].isin(hidden_child_fields)].reset_index(drop=True)


def maybe_finalize_computed_fields(current_chat_history):
    while True:
        next_field = tracker.get_next_field()
        if next_field == "BMI":
            computed_result = build_bmi_result()
            evidence = "由当前身高和当前体重自动计算"
        elif next_field in COMPUTED_SUMMARY_FIELDS:
            computed_result = build_summary_field_result(next_field)
            evidence = computed_result["evidence"]
        else:
            return next_field

        tracker.update_field(next_field, computed_result, evidence)
        add_assistant_message(build_confirmation_message(next_field, computed_result), current_chat_history)
        export_tracker_data()


def build_runtime_error_message(exc):
    if "DASHSCOPE_API_KEY" in str(exc):
        return "系统已启动，但尚未配置 DASHSCOPE_API_KEY，暂时无法调用大模型。请先在 Hugging Face Space Secrets 中添加该密钥。"
    return f"系统运行时出现错误: {exc}"


def clone_chat_history(history):
    return [dict(item) if isinstance(item, dict) else item for item in (history or [])]


def save_uploaded_report(uploaded_file, current_field=None):
    global last_report_output_path
    if not uploaded_file:
        last_report_output_path = ""
        return "未上传化验单。", "", None, gr.update(value=None), []

    uploaded_path = Path(uploaded_file)
    suffix = uploaded_path.suffix.lower()
    if suffix not in ALLOWED_REPORT_SUFFIXES:
        allowed_text = "、".join(sorted(ALLOWED_REPORT_SUFFIXES))
        last_report_output_path = ""
        return f"仅支持以下格式的化验单: {allowed_text}", "", None, gr.update(value=None), []

    if current_field == KIDNEY_ULTRASOUND_FIELD:
        patient_output_dir = get_session_patient_output_dir()
        student_id = get_active_student_id(snapshot_session_state())
        status, saved_path = save_report_file_only(
            str(uploaded_path),
            patient_name=PATIENT_NAME,
            student_id=student_id,
            field_name=current_field,
            **({"patient_output_dir": patient_output_dir} if patient_output_dir else {}),
        )
        last_report_output_path = ""
        if saved_path:
            status = f"{status}，已用于当前题：{current_field}"
        return status, saved_path or "", None, gr.update(value=None), []

    patient_output_dir = get_session_patient_output_dir()
    student_id = get_active_student_id(snapshot_session_state())
    status, output_path, rows = run_report_upload_flow_with_rows(
        str(uploaded_path),
        patient_name=PATIENT_NAME,
        student_id=student_id,
        field_name=current_field,
        **({"patient_output_dir": patient_output_dir} if patient_output_dir else {}),
    )
    last_report_output_path = output_path or ""
    if current_field and output_path:
        status = f"{status}，已用于当前题：{current_field}"
    return status, output_path or "", output_path or None, gr.update(value=None), rows


def build_upload_result(field, extracted_rows=None):
    if field == KIDNEY_ULTRASOUND_FIELD:
        return {
            "status": "done",
            "completion": "complete",
            "field_value": "已上传肾脏彩超",
            "confidence": 1.0,
            "reasoning": "用户已上传肾脏彩超图片，系统已保存原文件。",
            "evidence": "patient: 已上传肾脏彩超图片。",
        }

    extracted_value = extract_followup_value_from_rows(field, extracted_rows or [])
    if extracted_value:
        return {
            "status": "done",
            "completion": "complete",
            "field_value": extracted_value,
            "confidence": 1.0,
            "reasoning": "已根据上传化验单中的对应项目自动提取当前字段结果。",
            "evidence": f"patient: 已上传化验单。 extracted: {extracted_value}",
        }

    return {
        "status": "done",
        "completion": "complete",
        "field_value": "已上传化验单",
        "confidence": 1.0,
        "reasoning": "用户已通过上传控件补充化验单。",
        "evidence": "patient: 已上传化验单。",
    }


def advance_after_report_upload(current_chat_history, extracted_rows=None):
    global tracker
    updated_chat_history = clone_chat_history(current_chat_history)
    field = tracker.get_next_field()

    if field is None:
        df, file_path = export_tracker_data()
        return updated_chat_history, field, build_progress_html(), "化验单已上传。", file_path, df

    upload_result = build_upload_result(field, extracted_rows)
    tracker.update_field(field, upload_result)
    field_attempts.pop(field, None)
    add_assistant_message(build_confirmation_message(field, upload_result), updated_chat_history)

    df, file_path = export_tracker_data()
    next_field = maybe_finalize_computed_fields(updated_chat_history)
    df, file_path = export_tracker_data()

    parse_text = (
        "流程状态: done, 完整度: complete, 置信度: 1.0\n"
        f"解释: 已将当前问题更新为 {upload_result['field_value']}。"
    )
    if next_field is None:
        completion_msg = "所有信息已收集完成，请点击“导出结果”按钮下载随访结果。"
        add_assistant_message(completion_msg, updated_chat_history)
        return updated_chat_history, next_field, build_progress_html(), parse_text, file_path, df

    history_text = tracker.get_dialogue_history()
    question = generate_question(next_field, metadata, history_text)
    add_assistant_message(question, updated_chat_history)
    return updated_chat_history, next_field, build_progress_html(), parse_text, file_path, df


def handle_report_upload(session_state, uploaded_file, current_chat_history):
    with SESSION_LOCK:
        apply_session_state(session_state, session_scoped=True)
        active_student_id = str(session_state.get("student_id") or "").strip() if isinstance(session_state, dict) else ""
        active_followup_date = str(session_state.get("followup_date") or "").strip() if isinstance(session_state, dict) else ""
        patient_context = build_patient_context_html(PATIENT_NAME, active_student_id, active_followup_date, logged_in=True)
        current_field = tracker.get_next_field()
        status_text, saved_path, download_path, upload_reset, rows = save_uploaded_report(
            uploaded_file,
            current_field=current_field,
        )

        if not saved_path:
            df, file_path = export_tracker_data()
            upload_note, _, _, _, _ = build_upload_component_updates(current_field, clear_values=True)
            download_update, dataframe_update = build_result_component_updates(file_path, df, current_field)
            return (
                snapshot_session_state(),
                clone_chat_history(current_chat_history),
                current_field,
                patient_context,
                build_progress_html(),
                status_text,
                download_update,
                dataframe_update,
                gr.update(interactive=True),
                upload_note,
                upload_reset,
                status_text,
                "",
                download_path,
                gr.update(placeholder=get_input_placeholder(current_field)),
            )

        updated_chat_history, next_field, progress_text, parse_text, file_path, df = advance_after_report_upload(
            current_chat_history,
            rows,
        )
        upload_note, _, _, _, _ = build_upload_component_updates(next_field, clear_values=True)
        download_update, dataframe_update = build_result_component_updates(file_path, df, next_field)
        return (
            snapshot_session_state(),
            updated_chat_history,
            next_field,
            patient_context,
            progress_text,
            parse_text,
            download_update,
            dataframe_update,
            gr.update(interactive=True),
            upload_note,
            upload_reset,
            status_text,
            saved_path,
            download_path,
            gr.update(placeholder=get_input_placeholder(next_field)),
        )


def stream_assistant_messages(
    base_history,
    new_messages,
    current_field,
    patient_context_html,
    progress_text,
    parse_text,
    file_path,
    df,
):
    display_history = clone_chat_history(base_history)
    upload_note, upload_file_update, upload_status_update, upload_path_update, _ = build_upload_component_updates(current_field)
    current_placeholder = get_input_placeholder(current_field)
    for message in new_messages:
        role = message.get("role")
        if role != "assistant":
            display_history.append(dict(message))
            continue

        assistant_message = {"role": "assistant", "content": ""}
        display_history.append(assistant_message)
        full_text = message.get("content", "")
        chunk_size = 12 if len(full_text) > 120 else 6
        for index in range(chunk_size, len(full_text) + chunk_size, chunk_size):
            assistant_message["content"] = full_text[:index]
            yield (
                gr.update(value="", interactive=False, placeholder=current_placeholder),
                clone_chat_history(display_history),
                current_field,
                patient_context_html,
                progress_text,
                parse_text,
                file_path,
                df,
                gr.update(interactive=False),
                upload_note,
                upload_file_update,
                upload_status_update,
                upload_path_update,
                gr.update(),
            )
        assistant_message["content"] = full_text

    yield (
        gr.update(value="", interactive=True, placeholder=current_placeholder),
        clone_chat_history(display_history),
        current_field,
        patient_context_html,
        progress_text,
        parse_text,
        file_path,
        df,
        gr.update(interactive=True),
        upload_note,
        upload_file_update,
        upload_status_update,
        upload_path_update,
        gr.update(),
    )


def init_system(session_state=None, patient_name=DEFAULT_PATIENT_NAME):
    """初始化系统, 恢复到初始数据"""
    include_session_state = session_state is not None
    with SESSION_LOCK:
        active_state = apply_session_state(None, patient_name, session_scoped=include_session_state)

        _, file_path = export_tracker_data()

        greeting = "您好，我是医疗随访助手，需要了解您的健康状况。"
        add_assistant_message(greeting, chat_history)

        field = tracker.get_next_field()
        history_text = tracker.get_dialogue_history()
        try:
            question = generate_question(field, metadata, history_text)
        except Exception as exc:
            add_assistant_message(build_runtime_error_message(exc), chat_history)
            upload_note, upload_file_update, upload_status_update, upload_path_update, _ = build_upload_component_updates(field, clear_values=True)
            result = (
                snapshot_session_state(),
                "初始化系统失败",
                chat_history,
                field,
                build_progress_html(),
                file_path,
                pd.DataFrame(),
                upload_note,
                upload_file_update,
                upload_status_update,
                upload_path_update,
                gr.update(value=None),
                gr.update(placeholder=get_input_placeholder(field)),
            )
            if not include_session_state:
                return result[1:]
            return result

        add_assistant_message(question, chat_history)
        upload_note, upload_file_update, upload_status_update, upload_path_update, _ = build_upload_component_updates(field, clear_values=True)
        result = (
            snapshot_session_state(),
            "初始化系统成功",
            chat_history,
            field,
            build_progress_html(),
            file_path,
            pd.DataFrame(),
            upload_note,
            upload_file_update,
            upload_status_update,
            upload_path_update,
            gr.update(value=None),
            gr.update(placeholder=get_input_placeholder(field)),
        )
        if include_session_state:
            return result
        return result[1:]


def process_user_input(user_message, current_chat_history):
    """处理用户输入"""

    tracker.add_dialogue("Patient", user_message)
    current_chat_history.append({"role": "user", "content": user_message})

    field = tracker.get_next_field()
    history_text = tracker.get_dialogue_history()

    start_parse = time.time()
    try:
        raw_result = parse_answer(field, user_message, metadata[field]["描述"], history_text)
    except Exception as exc:
        error_message = build_runtime_error_message(exc)
        add_assistant_message(error_message, current_chat_history)
        df, file_path = export_tracker_data()
        return "", current_chat_history, field, build_progress_html(), error_message, file_path, df
    # 先把模型输出归一化，再用字段规则做一次“填表口径”校正。
    raw_result["field"] = field
    result = normalize_parse_result(raw_result)
    result = apply_field_completion_rules(field, result)
    end_parse = time.time()

    print(f"解析 parse_answer() 耗时：{end_parse - start_parse:.2f} 秒")
    print(f"AI提取的数据原始依据: {result['evidence']}")

    attempt_limit = get_field_attempt_limit(metadata, field)
    parse_output = (
        f"流程状态: {result['status']}, 完整度: {result['completion']}, 置信度: {result['confidence']}\n"
        f"解释: {result['reasoning']}"
    )

    status_for_question = None
    field_finished = is_final_status(result["status"])

    if result["status"] == "ask_again":
        field_attempts[field] = field_attempts.get(field, 0) + 1
        current_attempts = field_attempts[field]
        parse_output += f"\n追问进度: {current_attempts}/{attempt_limit}"

        if current_attempts >= attempt_limit:
            result = finalize_after_attempt_limit(result)
            tracker.update_field(field, result)
            field_attempts.pop(field, None)
            add_assistant_message(build_confirmation_message(field, result), current_chat_history)
            field_finished = True
        else:
            status_for_question = "ask_again"
            field_finished = False
    else:
        tracker.update_field(field, result)
        field_attempts.pop(field, None)
        add_assistant_message(build_confirmation_message(field, result), current_chat_history)

    df, file_path = export_tracker_data()

    if field_finished:
        field = maybe_finalize_computed_fields(current_chat_history)
        df, file_path = export_tracker_data()
    else:
        field = tracker.get_next_field()

    if field is None:
        completion_msg = "所有信息已收集完成，请点击“导出结果”按钮下载随访结果。"
        add_assistant_message(completion_msg, current_chat_history)
        return "", current_chat_history, field, build_progress_html(), parse_output, file_path, df

    history_text = tracker.get_dialogue_history()
    start_question = time.time()
    try:
        question = generate_question(
            field,
            metadata,
            history_text,
            status_for_question or "first_ask",
        )
    except Exception as exc:
        error_message = build_runtime_error_message(exc)
        add_assistant_message(error_message, current_chat_history)
        return "", current_chat_history, field, build_progress_html(), error_message, file_path, df
    end_question = time.time()
    print(f"生成问题 generate_question() 耗时：{end_question - start_question:.2f} 秒")
    add_assistant_message(question, current_chat_history)

    return "", current_chat_history, field, build_progress_html(), parse_output, file_path, df



def download_data(session_state=None, patient_name=None):
    with SESSION_LOCK:
        apply_session_state(session_state, patient_name, session_scoped=session_state is not None)
        student_id = get_active_student_id(session_state) or get_active_student_id(snapshot_session_state())
        followup_date = get_active_followup_date(session_state) or get_active_followup_date(snapshot_session_state())
        file_path = get_runtime_excel_path()
        if not os.path.exists(file_path):
            _, generated_path = export_tracker_data()
            file_path = Path(generated_path)
        return persist_followup_export(
            file_path,
            uploaded_report_path=last_report_output_path or None,
            patient_name=PATIENT_NAME,
            student_id=student_id,
            followup_date=followup_date,
        )


def on_edit(session_state=None, patient_name=None, edited_df=None):
    """Save edited dataframe."""
    if edited_df is None:
        edited_df = session_state
        session_state = None
        patient_name = None
    with SESSION_LOCK:
        apply_session_state(session_state, patient_name, session_scoped=session_state is not None)
        excel_file = get_runtime_excel_path()
        edited_df.copy().to_excel(excel_file, index=False, engine="openpyxl")
        format_excel(excel_file, excel_file)
        return gr.update(value="Saved"), gr.update(value=download_data)


def respond(*args):
    if len(args) == 2:
        current_session_state = None
        patient_name = DEFAULT_PATIENT_NAME
        message, current_chat_history = args
        include_session_state = False
    elif len(args) == 4:
        current_session_state, patient_name, message, current_chat_history = args
        include_session_state = True
    else:
        raise TypeError("respond expects either (message, chat_history) or (session_state, patient_name, message, chat_history)")

    def finalize_payload(payload):
        if include_session_state:
            return (snapshot_session_state(), *payload)
        reduced_payload = list(payload)
        if len(reduced_payload) >= 4:
            reduced_payload.pop(3)
        return tuple(reduced_payload)

    with SESSION_LOCK:
        apply_session_state(current_session_state, patient_name, session_scoped=include_session_state)
        active_student_id = ""
        if isinstance(current_session_state, dict):
            active_student_id = str(current_session_state.get("student_id") or "").strip()
        active_followup_date = ""
        if isinstance(current_session_state, dict):
            active_followup_date = str(current_session_state.get("followup_date") or "").strip()
        if include_session_state and (not str(patient_name or "").strip() or not active_student_id):
            payload = (
                gr.update(value="", interactive=False, placeholder="请先填写患者姓名和学工号"),
                clone_chat_history(chat_history),
                gr.update(),
                build_patient_context_html(message="请先填写患者姓名和学工号，然后点击“开始随访”。"),
                gr.update(),
                "请先填写患者姓名和学工号，然后点击“开始随访”。",
                gr.update(),
                gr.update(),
                gr.update(interactive=True),
                gr.update(value="", visible=False),
                gr.update(value=None, visible=False),
                gr.update(value="", visible=False),
                gr.update(value="", visible=False),
                gr.update(),
            )
            yield finalize_payload(payload)
            return
        if not message or not message.strip():
            payload = (
                gr.update(value="", interactive=True, placeholder=get_input_placeholder(tracker.get_next_field())),
                clone_chat_history(chat_history),
                gr.update(),
                build_patient_context_html(PATIENT_NAME, active_student_id, active_followup_date, logged_in=include_session_state),
                gr.update(),
                "请输入内容后再发送。",
                gr.update(),
                gr.update(),
                gr.update(interactive=True),
                gr.update(),
                gr.update(),
                gr.update(),
                gr.update(),
                gr.update(),
            )
            yield finalize_payload(payload)
            return

        base_history = clone_chat_history(chat_history)
        pending_history = clone_chat_history(base_history)
        pending_history.append({"role": "user", "content": message})
        payload = (
            gr.update(value="", interactive=False),
            pending_history,
            gr.update(),
            build_patient_context_html(PATIENT_NAME, active_student_id, active_followup_date, logged_in=include_session_state),
            gr.update(),
            "正在解析并生成回复，请稍候...",
            gr.update(),
            gr.update(),
            gr.update(interactive=False),
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
        )
        yield finalize_payload(payload)

        _, updated_chat_history, current_field, progress_text, parse_text, file_path, df = process_user_input(message, base_history)
        new_messages = updated_chat_history[len(chat_history or []):]
        assistant_messages = [item for item in new_messages if item.get("role") == "assistant"]
        download_update, dataframe_update = build_result_component_updates(file_path, df, current_field)

        if not assistant_messages:
            upload_note, upload_file_update, upload_status_update, upload_path_update, msg_placeholder_update = build_upload_component_updates(current_field)
            payload = (
                gr.update(value="", interactive=True, **msg_placeholder_update),
                updated_chat_history,
                current_field,
                build_patient_context_html(PATIENT_NAME, active_student_id, active_followup_date, logged_in=include_session_state),
                progress_text,
                parse_text,
                download_update,
                dataframe_update,
                gr.update(interactive=True),
                upload_note,
                upload_file_update,
                upload_status_update,
                upload_path_update,
                gr.update(),
            )
            yield finalize_payload(payload)
            return

        for payload in stream_assistant_messages(
            pending_history,
            assistant_messages,
            current_field,
            build_patient_context_html(PATIENT_NAME, active_student_id, active_followup_date, logged_in=include_session_state),
            progress_text,
            parse_text,
            download_update,
            dataframe_update,
        ):
            yield finalize_payload(payload)


with gr.Blocks(title="AI医疗随访系统") as demo:
    session_state = gr.State(build_session_state(DEFAULT_PATIENT_NAME))
    with gr.Column(elem_classes=["app-shell"]):
        with gr.Row(elem_classes=["workspace-row"]):
            with gr.Column(scale=1, elem_classes=["sidebar-card", "sidebar-stack"]):
                gr.Markdown("### 随访进度", elem_classes=["section-title"])
                patient_name_input = gr.Textbox(
                    label="患者姓名",
                    value="",
                    placeholder="请输入当前患者姓名",
                    elem_classes=["compact-box", "metric-box"],
                )
                student_id_input = gr.Textbox(
                    label="学工号",
                    value="",
                    placeholder="请输入当前患者学工号",
                    elem_classes=["compact-box", "metric-box"],
                )
                followup_date_input = gr.Textbox(
                    label="随访日期",
                    value="",
                    placeholder="可手动输入，如 2025.06.12；留空则按默认/当天日期",
                    elem_classes=["compact-box", "metric-box"],
                )
                with gr.Group(elem_classes=["sidebar-primary"]):
                    progress_output = gr.HTML(build_progress_html(), visible=False)
                with gr.Row(elem_classes=["button-row"]):
                    start_btn = gr.Button("开始随访", variant="primary", elem_classes=["primary-action"])
                    init_btn = gr.Button("重新开始", visible=False, elem_classes=["soft-action"])
                    download_btn = gr.DownloadButton(label="导出结果", value=download_data, visible=False, elem_classes=["soft-action"])
                with gr.Accordion("查看详细状态", open=False, elem_classes=["compact-accordion"]):
                    question_output = gr.Textbox(label="当前问题主题", interactive=False, elem_classes=["compact-box", "metric-box"])
                    status_output = gr.Textbox(label="系统状态", interactive=False, elem_classes=["compact-box", "metric-box"])
                    parse_output = gr.Textbox(label="系统识别详情", lines=4, interactive=False, elem_classes=["compact-box", "long-box"])
            with gr.Column(scale=4, elem_classes=["chat-card"]):
                gr.Markdown("### 随访对话", elem_classes=["section-title"])
                patient_context_output = gr.HTML(
                    build_patient_context_html(message="请先填写患者姓名和学工号，然后点击“开始随访”。"),
                )
                gr.HTML(
                    """
                    <div class="chat-head">
                        请根据问题直接回答；如果暂时不清楚，也可以回复“不知道”或“稍后补充”。
                    </div>
                    """
                )
                chatbot = gr.Chatbot(label="对话记录", height=620, layout="bubble")
                with gr.Row(elem_classes=["composer-row"]):
                    msg = gr.Textbox(
                        label="请输入您的回答",
                        placeholder="请先填写患者姓名和学工号",
                        lines=1,
                        interactive=False,
                        elem_classes=["compact-box"]
                    )
                    submit_btn = gr.Button("发送", variant="primary", interactive=False, elem_classes=["primary-action", "chat-actions"])
                upload_stage_note = gr.HTML(
                    build_upload_stage_note(tracker.get_next_field()),
                    visible=False,
                    elem_classes=["inline-upload-shell"],
                )
                report_upload = gr.File(
                    label="上传化验单（.docx/.png/.jpg/.jpeg）",
                    file_types=ALLOWED_REPORT_FILE_TYPES,
                    type="filepath",
                    visible=False,
                    elem_classes=["upload-card"],
                )
                report_status = gr.Textbox(
                    label="上传状态",
                    interactive=False,
                    visible=False,
                    elem_classes=["compact-box", "metric-box"],
                )
                report_saved_path = gr.Textbox(
                    label="文件保存位置",
                    interactive=False,
                    visible=False,
                    elem_classes=["compact-box", "long-box"],
                )
                report_download_output = gr.DownloadButton(
                    label="下载化验单结果",
                    visible=True,
                    elem_id="auto-report-download",
                )

        with gr.Column(elem_classes=["data-card"]):
            gr.Markdown("### 结果校对", elem_classes=["section-title"])
            gr.Markdown("如需人工修正，可展开下方表格直接编辑，导出时会保留修改结果。", elem_classes=["chat-tip"])
            with gr.Accordion("展开或收起随访数据表", open=False, elem_classes=["data-shell"]):
                dataframe_output = gr.Dataframe(label="文件内容", interactive=True, visible=False)

    start_btn.click(
        fn=start_followup,
        inputs=[session_state, patient_name_input, student_id_input, followup_date_input],
        outputs=[
            session_state,
            status_output,
            chatbot,
            question_output,
            patient_context_output,
            progress_output,
            parse_output,
            download_btn,
            dataframe_output,
            submit_btn,
            upload_stage_note,
            report_upload,
            report_status,
            report_saved_path,
            report_download_output,
            msg,
        ],
    )
    init_btn.click(
        fn=start_followup,
        inputs=[session_state, patient_name_input, student_id_input, followup_date_input],
        outputs=[
            session_state,
            status_output,
            chatbot,
            question_output,
            patient_context_output,
            progress_output,
            parse_output,
            download_btn,
            dataframe_output,
            submit_btn,
            upload_stage_note,
            report_upload,
            report_status,
            report_saved_path,
            report_download_output,
            msg,
        ],
    )
    demo.load(
        fn=build_login_required_view,
        inputs=[session_state, patient_name_input, student_id_input, followup_date_input],
        outputs=[
            session_state,
            status_output,
            chatbot,
            question_output,
            patient_context_output,
            progress_output,
            parse_output,
            download_btn,
            dataframe_output,
            submit_btn,
            upload_stage_note,
            report_upload,
            report_status,
            report_saved_path,
            report_download_output,
            msg,
        ],
    )
    patient_name_input.input(
        fn=normalize_patient_name_input,
        inputs=patient_name_input,
        outputs=patient_name_input,
    )
    student_id_input.input(
        fn=normalize_student_id_input,
        inputs=student_id_input,
        outputs=student_id_input,
    )
    followup_date_input.input(
        fn=normalize_followup_date_input,
        inputs=followup_date_input,
        outputs=followup_date_input,
    )
    download_btn.click(
        fn=download_data,
        inputs=[session_state, patient_name_input],
        outputs=download_btn,
    )
    dataframe_output.edit(
        fn=on_edit,
        inputs=[session_state, patient_name_input, dataframe_output],
        outputs=[status_output, download_btn],
    )
    report_upload_event = report_upload.upload(
        fn=handle_report_upload,
        inputs=[session_state, report_upload, chatbot],
        outputs=[
            session_state,
            chatbot,
            question_output,
            patient_context_output,
            progress_output,
            parse_output,
            download_btn,
            dataframe_output,
            submit_btn,
            upload_stage_note,
            report_upload,
            report_status,
            report_saved_path,
            report_download_output,
            msg,
        ],
    )
    report_upload_event.then(
        fn=None,
        js=AUTO_REPORT_DOWNLOAD_JS,
    )

    msg.submit(
        fn=respond,
        inputs=[session_state, patient_name_input, msg, chatbot],
        outputs=[
            session_state,
            msg,
            chatbot,
            question_output,
            patient_context_output,
            progress_output,
            parse_output,
            download_btn,
            dataframe_output,
            submit_btn,
            upload_stage_note,
            report_upload,
            report_status,
            report_saved_path,
            report_download_output,
        ],
    )
    submit_btn.click(
        fn=respond,
        inputs=[session_state, patient_name_input, msg, chatbot],
        outputs=[
            session_state,
            msg,
            chatbot,
            question_output,
            patient_context_output,
            progress_output,
            parse_output,
            download_btn,
            dataframe_output,
            submit_btn,
            upload_stage_note,
            report_upload,
            report_status,
            report_saved_path,
            report_download_output,
        ],
    )


# 保留原有的 main_flow 函数，但不再直接调用
def main_flow(excel_path):
    """原有的主流程函数，现在通过 Gradio 界面调用"""
    pass


if __name__ == "__main__":
    demo.launch(css=CUSTOM_CSS)
