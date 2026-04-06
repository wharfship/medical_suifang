from Model_initialization import *
import gradio as gr
import os
import re
import shutil
import time
from pathlib import Path

from excel_adjusting import *
from field_rules import apply_field_completion_rules
from workflow_status import (
    finalize_after_attempt_limit,
    get_field_attempt_limit,
    is_final_status,
    normalize_parse_result,
)


BASE_DIR = Path(__file__).resolve().parent
template_candidates = sorted(BASE_DIR.glob("2025.5.28*excel*.xls"))
if not template_candidates:
    raise FileNotFoundError(f"Excel template not found in {BASE_DIR}")
excel_path = template_candidates[0]
metadata = load_excel_template(excel_path)
tracker = FieldStateTracker(metadata)
field_attempts = {}
chat_history = []   # 专门给 gradio 的 Chatbot 用的

ALLOWED_REPORT_SUFFIXES = {".doc", ".docx", ".pdf", ".png", ".jpg", ".jpeg"}
ALLOWED_REPORT_FILE_TYPES = [".doc", ".docx", ".pdf", ".png", ".jpg", ".jpeg"]

CUSTOM_CSS = """
.gradio-container {
    background:
        radial-gradient(circle at top left, rgba(92, 180, 255, 0.18), transparent 28%),
        radial-gradient(circle at top right, rgba(35, 130, 255, 0.12), transparent 30%),
        linear-gradient(180deg, #f4f8ff 0%, #eef4fb 100%);
}

.app-shell {
    max-width: 1320px;
    margin: 0 auto;
    padding: 18px 0 10px;
}

.hero-card,
.sidebar-card,
.chat-card,
.data-card {
    border: 1px solid rgba(117, 142, 168, 0.18);
    border-radius: 22px;
    background: rgba(255, 255, 255, 0.92);
    box-shadow: 0 18px 45px rgba(44, 77, 117, 0.10);
    backdrop-filter: blur(12px);
}

.hero-card {
    padding: 24px 28px 10px;
    margin-bottom: 14px;
    overflow: hidden;
}

.hero-card h1 {
    margin: 0;
    font-size: 2.1rem;
    font-weight: 800;
    letter-spacing: -0.03em;
    color: #15304f;
}

.hero-card p {
    margin: 10px 0 12px;
    color: #4f647a;
    font-size: 1rem;
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

.sidebar-card,
.chat-card,
.data-card {
    padding: 10px;
}

.section-title {
    margin: 4px 0 12px;
    padding: 2px 6px;
    color: #193b5e;
    font-size: 1.02rem;
    font-weight: 700;
}

.compact-box textarea,
.compact-box input {
    border-radius: 16px !important;
}

.chat-card .bubble-wrap,
.chat-card .message-wrap {
    font-size: 0.98rem;
}

.chat-actions {
    margin-top: 8px;
}

.primary-action button {
    background: linear-gradient(135deg, #1b7bff 0%, #1662d6 100%) !important;
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
    margin-bottom: 12px;
    padding-bottom: 6px;
    border-bottom: 1px dashed rgba(117, 142, 168, 0.28);
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


def build_progress_text():
    total_fields = len(metadata)
    completed_fields = len(tracker.filled_data)
    if total_fields == 0:
        return "0/0 (0%)"

    progress_ratio = completed_fields / total_fields
    progress_percent = round(progress_ratio * 100)
    return f"{completed_fields}/{total_fields} ({progress_percent}%)"


def export_tracker_data():
    df = pd.DataFrame(tracker.get_parse_history())
    df = df.rename(columns=COLUMN_NAMES)
    excel_file = BASE_DIR / "medical_data.xlsx"
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


def maybe_finalize_bmi(current_chat_history):
    next_field = tracker.get_next_field()
    if next_field != "BMI":
        return next_field

    bmi_result = build_bmi_result()
    tracker.update_field(next_field, bmi_result, "由当前身高和当前体重自动计算")
    add_assistant_message(build_confirmation_message(next_field, bmi_result), current_chat_history)
    export_tracker_data()
    return tracker.get_next_field()


def build_runtime_error_message(exc):
    if "DASHSCOPE_API_KEY" in str(exc):
        return "系统已启动，但尚未配置 DASHSCOPE_API_KEY，暂时无法调用大模型。请先在 Hugging Face Space Secrets 中添加该密钥。"
    return f"系统运行时出现错误: {exc}"


def clone_chat_history(history):
    return [dict(item) if isinstance(item, dict) else item for item in (history or [])]


def save_uploaded_report(uploaded_file):
    if not uploaded_file:
        return "未上传化验单。", ""

    uploaded_path = Path(uploaded_file)
    suffix = uploaded_path.suffix.lower()
    if suffix not in ALLOWED_REPORT_SUFFIXES:
        allowed_text = "、".join(sorted(ALLOWED_REPORT_SUFFIXES))
        return f"仅支持以下格式的化验单: {allowed_text}", ""

    upload_dir = BASE_DIR / "uploaded_reports"
    upload_dir.mkdir(exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    target_path = upload_dir / f"{timestamp}_{uploaded_path.name}"
    shutil.copy2(uploaded_path, target_path)
    return f"化验单已上传: {target_path.name}", str(target_path)


def stream_assistant_messages(
    base_history,
    new_messages,
    current_field,
    progress_text,
    parse_text,
    file_path,
    df,
):
    display_history = clone_chat_history(base_history)
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
                gr.update(value="", interactive=False),
                clone_chat_history(display_history),
                current_field,
                progress_text,
                parse_text,
                file_path,
                df,
                gr.update(interactive=False),
            )
        assistant_message["content"] = full_text

    yield (
        gr.update(value="", interactive=True),
        clone_chat_history(display_history),
        current_field,
        progress_text,
        parse_text,
        file_path,
        df,
        gr.update(interactive=True),
    )


def init_system():
    """初始化系统, 恢复到初始数据"""
    global tracker, metadata
    metadata = load_excel_template(excel_path)
    tracker = FieldStateTracker(metadata)
    field_attempts.clear()
    chat_history.clear()

    _, file_path = export_tracker_data()

    greeting = "您好，我是医疗随访助手，需要了解您的健康状况。"
    add_assistant_message(greeting, chat_history)

    field = tracker.get_next_field()
    history_text = tracker.get_dialogue_history()
    try:
        question = generate_question(field, metadata, history_text)
    except Exception as exc:
        add_assistant_message(build_runtime_error_message(exc), chat_history)
        return "初始化系统失败", chat_history, field, build_progress_text(), file_path, pd.DataFrame()

    add_assistant_message(question, chat_history)
    return "初始化系统成功", chat_history, field, build_progress_text(), file_path, pd.DataFrame()


def process_user_input(user_message, chat_history):
    """处理用户输入"""
    global tracker, field_attempts

    tracker.add_dialogue("Patient", user_message)
    chat_history.append({"role": "user", "content": user_message})

    field = tracker.get_next_field()
    history_text = tracker.get_dialogue_history()

    start_parse = time.time()
    try:
        raw_result = parse_answer(field, user_message, metadata[field]["描述"], history_text)
    except Exception as exc:
        error_message = build_runtime_error_message(exc)
        add_assistant_message(error_message, chat_history)
        df, file_path = export_tracker_data()
        return "", chat_history, field, build_progress_text(), error_message, file_path, df
    # 先把模型输出归一化，再用字段规则做一次“填表口径”校正。
    result = normalize_parse_result(raw_result)
    result = apply_field_completion_rules(field, result)
    end_parse = time.time()

    print(f"🔍 解析 parse_answer() 耗时：{end_parse - start_parse:.2f} 秒")
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
            add_assistant_message(build_confirmation_message(field, result), chat_history)
            field_finished = True
        else:
            status_for_question = "ask_again"
            field_finished = False
    else:
        tracker.update_field(field, result)
        field_attempts.pop(field, None)
        add_assistant_message(build_confirmation_message(field, result), chat_history)

    df, file_path = export_tracker_data()

    if field_finished:
        field = maybe_finalize_bmi(chat_history)
        df, file_path = export_tracker_data()
    else:
        field = tracker.get_next_field()

    if field is None:
        completion_msg = "所有信息已收集完成，请您点击左上角“导出并下载”按钮进行下载！"
        add_assistant_message(completion_msg, chat_history)
        return "", chat_history, field, build_progress_text(), parse_output, file_path, df

    history_text = tracker.get_dialogue_history()
    start_question = time.time()
    try:
        question = generate_question(field, metadata, history_text, status_for_question or "first_ask")
    except Exception as exc:
        error_message = build_runtime_error_message(exc)
        add_assistant_message(error_message, chat_history)
        return "", chat_history, field, build_progress_text(), error_message, file_path, df
    end_question = time.time()
    print(f"🔍 生成问题 generate_question() 耗时：{end_question - start_question:.2f} 秒")
    add_assistant_message(question, chat_history)

    return "", chat_history, field, build_progress_text(), parse_output, file_path, df



def download_data():
    file_path = BASE_DIR / "medical_data.xlsx"
    if not os.path.exists(file_path):
        _, generated_path = export_tracker_data()
        return generated_path
    return str(file_path)


def on_edit(edited_df):
    """Save edited dataframe."""
    excel_file = BASE_DIR / "medical_data.xlsx"
    edited_df.copy().to_excel(excel_file, index=False, engine="openpyxl")
    format_excel(excel_file, excel_file)
    return gr.update(value="Saved" ), str(excel_file)


with gr.Blocks(title="AI医疗随访系统") as demo:
    with gr.Column(elem_classes=["app-shell"]):
        gr.HTML(
            """
            <div class="hero-card">
                <div class="hero-badges">
                    <span>医疗随访助手</span>
                    <span>结构化信息采集</span>
                    <span>支持化验单上传</span>
                </div>
                <h1>AI 医疗随访对话系统</h1>
                <p>保留现有随访流程与导出能力，在同一页面里完成对话采集、结果校对与化验单整理。</p>
            </div>
            """
        )

        with gr.Row():
            with gr.Column(scale=1, elem_classes=["sidebar-card"]):
                gr.Markdown("### 工具面板", elem_classes=["section-title"])
                with gr.Group(elem_classes=["upload-card"]):
                    report_upload = gr.File(
                        label="上传化验单（.doc/.docx/.pdf/.png/.jpg）",
                        file_types=ALLOWED_REPORT_FILE_TYPES,
                        type="filepath",
                    )
                    report_status = gr.Textbox(label="上传状态", interactive=False, elem_classes=["compact-box"])
                    report_saved_path = gr.Textbox(label="文件保存位置", interactive=False, elem_classes=["compact-box"])

                init_btn = gr.Button("初始化系统", variant="primary", elem_classes=["primary-action"])
                download_btn = gr.DownloadButton(label="导出并下载", value=download_data, visible=True, elem_classes=["soft-action"])
                status_output = gr.Textbox(label="系统状态", interactive=False, elem_classes=["compact-box"])
                parse_output = gr.Textbox(label="上一问题解析情况", lines=3, interactive=False, elem_classes=["compact-box"])
                question_output = gr.Textbox(label="当前字段", interactive=False, elem_classes=["compact-box"])
                progress_output = gr.Textbox(label="当前进度", interactive=False, elem_classes=["compact-box"])
            with gr.Column(scale=3, elem_classes=["chat-card"]):
                gr.Markdown("### 随访对话", elem_classes=["section-title"])
                chatbot = gr.Chatbot(label="对话记录", height=520, layout="bubble")
                msg = gr.Textbox(
                    label="请输入您的回答",
                    placeholder="在这里输入您的回答...",
                    lines=1,
                    elem_classes=["compact-box"]
                )
                submit_btn = gr.Button("发送", variant="primary", elem_classes=["primary-action", "chat-actions"])

        with gr.Column(elem_classes=["data-card"]):
            gr.Markdown("### 随访数据表", elem_classes=["section-title"])
            dataframe_output = gr.Dataframe(label="文件内容", interactive=True)

    init_btn.click(fn=init_system, outputs=[status_output, chatbot, question_output, progress_output, download_btn, dataframe_output])
    demo.load(fn=init_system, outputs=[status_output, chatbot, question_output, progress_output, download_btn, dataframe_output])
    download_btn.click(fn=download_data, outputs=download_btn)
    dataframe_output.edit(fn=on_edit, inputs=dataframe_output, outputs=[status_output, download_btn])
    report_upload.upload(fn=save_uploaded_report, inputs=report_upload, outputs=[report_status, report_saved_path])

    def respond(message, chat_history):
        if not message or not message.strip():
            yield (
                gr.update(value="", interactive=True),
                clone_chat_history(chat_history),
                gr.update(),
                gr.update(),
                "请输入内容后再发送。",
                gr.update(),
                gr.update(),
                gr.update(interactive=True),
            )
            return

        base_history = clone_chat_history(chat_history)
        pending_history = clone_chat_history(base_history)
        pending_history.append({"role": "user", "content": message})
        yield (
            gr.update(value="", interactive=False),
            pending_history,
            gr.update(),
            gr.update(),
            "正在解析并生成回复，请稍候...",
            gr.update(),
            gr.update(),
            gr.update(interactive=False),
        )

        _, updated_chat_history, current_field, progress_text, parse_text, file_path, df = process_user_input(message, base_history)
        new_messages = updated_chat_history[len(chat_history or []):]
        assistant_messages = [item for item in new_messages if item.get("role") == "assistant"]

        if not assistant_messages:
            yield (
                gr.update(value="", interactive=True),
                updated_chat_history,
                current_field,
                progress_text,
                parse_text,
                file_path,
                df,
                gr.update(interactive=True),
            )
            return

        yield from stream_assistant_messages(
            pending_history,
            assistant_messages,
            current_field,
            progress_text,
            parse_text,
            file_path,
            df,
        )

    msg.submit(fn=respond, inputs=[msg, chatbot], outputs=[msg, chatbot, question_output, progress_output, parse_output, download_btn, dataframe_output, submit_btn])
    submit_btn.click(fn=respond, inputs=[msg, chatbot], outputs=[msg, chatbot, question_output, progress_output, parse_output, download_btn, dataframe_output, submit_btn])


# 保留原有的 main_flow 函数，但不再直接调用
def main_flow(excel_path):
    """原有的主流程函数，现在通过 Gradio 界面调用"""
    pass


if __name__ == "__main__":
    demo.launch(css=CUSTOM_CSS)
