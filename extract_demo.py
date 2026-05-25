import tempfile

import gradio as gr
import pandas as pd

from lab_report_extractor import (
    build_display_rows,
    export_rows_to_xlsx,
    extract_lab_items_from_file,
)


def run_extraction(file_path):
    if not file_path:
        return "请先上传文件。", pd.DataFrame(columns=["项目名称", "结果", "单位"]), None

    try:
        rows = extract_lab_items_from_file(file_path)
    except Exception as exc:
        return f"提取失败：{exc}", pd.DataFrame(columns=["项目名称", "结果", "单位"]), None

    display_rows = build_display_rows(rows)
    output_path = export_rows_to_xlsx(rows, tempfile.gettempdir(), "lab_extract_result")
    return "提取完成", pd.DataFrame(display_rows), output_path


with gr.Blocks(title="化验单提取演示") as demo:
    gr.Markdown("## 化验单提取演示")
    file_input = gr.File(
        label="上传 .docx 或图片",
        type="filepath",
        file_types=[".docx", ".png", ".jpg", ".jpeg"],
    )
    extract_button = gr.Button("开始提取", variant="primary")
    status_output = gr.Textbox(label="状态", interactive=False)
    table_output = gr.Dataframe(label="提取结果", interactive=False)
    file_output = gr.File(label="下载 xlsx")

    extract_button.click(
        fn=run_extraction,
        inputs=file_input,
        outputs=[status_output, table_output, file_output],
    )


if __name__ == "__main__":
    demo.launch()
