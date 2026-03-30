from Model_initialization import *
import gradio as gr
import os
import re
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


COLUMN_NAMES = {
    "field": "填写内容",
    "value": "填写数据",
    "completion": "完整度",
    "status": "流程状态",
    "reasoning": "解释",
    "evidence": "数据原始依据",
}


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
        return "初始化系统失败", chat_history, field, file_path, pd.DataFrame()

    add_assistant_message(question, chat_history)
    return "初始化系统成功", chat_history, field, file_path, pd.DataFrame()


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
        return "", chat_history, field, error_message, file_path, df
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
        return "", chat_history, field, parse_output, file_path, df

    history_text = tracker.get_dialogue_history()
    start_question = time.time()
    try:
        question = generate_question(field, metadata, history_text, status_for_question or "first_ask")
    except Exception as exc:
        error_message = build_runtime_error_message(exc)
        add_assistant_message(error_message, chat_history)
        return "", chat_history, field, error_message, file_path, df
    end_question = time.time()
    print(f"🔍 生成问题 generate_question() 耗时：{end_question - start_question:.2f} 秒")
    add_assistant_message(question, chat_history)

    return "", chat_history, field, parse_output, file_path, df



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
    gr.Markdown("# AI医疗随访对话系统")
    gr.Markdown("AI对话系统")

    with gr.Row():
        with gr.Column(scale=1):
            init_btn = gr.Button("初始化系统", variant="primary")
            download_btn = gr.DownloadButton(label="导出并下载", value=download_data, visible=True)
            status_output = gr.Textbox(label="系统状态")
            parse_output = gr.Textbox(label="上一问题解析情况", lines=3)
            question_output = gr.Textbox(label="当前字段")
        with gr.Column(scale=3):
            chatbot = gr.Chatbot(label="对话记录", height=500, layout="bubble")
            msg = gr.Textbox(
                label="请输入您的回答",
                placeholder="在这里输入您的回答...",
                lines=1
            )
            submit_btn = gr.Button("发送", variant="primary")
    dataframe_output = gr.Dataframe(label="文件内容", interactive=True)

    init_btn.click(fn=init_system, outputs=[status_output, chatbot, question_output, download_btn, dataframe_output])
    demo.load(fn=init_system, outputs=[status_output, chatbot, question_output, download_btn, dataframe_output])
    download_btn.click(fn=download_data, outputs=download_btn)
    dataframe_output.edit(fn=on_edit, inputs=dataframe_output, outputs=[status_output, download_btn])

    def respond(message, chat_history):
        _, updated_chat_history, current_field, parse_text, file_path, df = process_user_input(message, chat_history)
        return "", updated_chat_history, current_field, parse_text, file_path, df

    msg.submit(fn=respond, inputs=[msg, chatbot], outputs=[msg, chatbot, question_output, parse_output, download_btn, dataframe_output])
    submit_btn.click(fn=respond, inputs=[msg, chatbot], outputs=[msg, chatbot, question_output, parse_output, download_btn, dataframe_output])


# 保留原有的 main_flow 函数，但不再直接调用
def main_flow(excel_path):
    """原有的主流程函数，现在通过 Gradio 界面调用"""
    pass


if __name__ == "__main__":
    demo.launch()
