import gradio as gr

from report_upload_flow import run_report_upload_flow


def run_extraction(file_path):
    return run_report_upload_flow(file_path)


AUTO_DOWNLOAD_JS = """
() => {
    const button = document.querySelector('#auto-download button');
    if (button) {
        setTimeout(() => button.click(), 150);
    }
}
"""


CUSTOM_CSS = """
#auto-download {
    display: none !important;
}
"""


with gr.Blocks(title="化验单提取演示") as demo:
    gr.Markdown("## 化验单提取演示")
    file_input = gr.File(
        label="上传 .docx 或图片",
        type="filepath",
        file_types=[".docx", ".png", ".jpg", ".jpeg"],
    )
    extract_button = gr.Button("开始提取", variant="primary")
    status_output = gr.Textbox(label="状态", interactive=False)
    download_output = gr.DownloadButton(
        label="下载结果",
        visible=True,
        elem_id="auto-download",
    )

    extract_event = extract_button.click(
        fn=run_extraction,
        inputs=file_input,
        outputs=[status_output, download_output],
    )
    extract_event.then(
        fn=None,
        js=AUTO_DOWNLOAD_JS,
    )


if __name__ == "__main__":
    demo.launch(css=CUSTOM_CSS)
