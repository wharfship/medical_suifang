# Lab Report Vision Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone Gradio demo that extracts `项目名称`、`结果`、`单位` from the first patient in an uploaded `.docx` or image lab report and exports the result as `xlsx`.

**Architecture:** Add one focused extraction module that turns an uploaded file into an image payload, calls the DashScope OpenAI-compatible vision API, normalizes the response, and writes an Excel file. Keep the demo UI in a separate entrypoint so the main follow-up app remains untouched.

**Tech Stack:** Python, Gradio, pandas, openpyxl, OpenAI SDK, zipfile, base64, unittest

---

### Task 1: Add tests for result cleaning and xlsx export

**Files:**
- Create: `tests/test_lab_report_extractor.py`
- Test: `tests/test_lab_report_extractor.py`

- [ ] **Step 1: Write the failing test**

```python
import os
import tempfile
import unittest

import pandas as pd

from lab_report_extractor import export_rows_to_xlsx, normalize_extracted_items


class NormalizeExtractedItemsTests(unittest.TestCase):
    def test_normalize_filters_empty_rows_and_deduplicates(self):
        rows = [
            {"项目名称": "肌酐", "结果": "66", "单位": "umol/L"},
            {"项目名称": "肌酐", "结果": "66", "单位": "umol/L"},
            {"项目名称": "尿素", "结果": "", "单位": "mmol/L"},
            {"项目名称": "", "结果": "5.2", "单位": "mmol/L"},
            {"项目名称": "尿酸", "结果": "420", "单位": "umol/L"},
        ]

        normalized = normalize_extracted_items(rows)

        self.assertEqual(
            normalized,
            [
                {"项目名称": "肌酐", "结果": "66", "单位": "umol/L"},
                {"项目名称": "尿酸", "结果": "420", "单位": "umol/L"},
            ],
        )


class ExportRowsToXlsxTests(unittest.TestCase):
    def test_export_writes_expected_columns(self):
        rows = [{"项目名称": "肌酐", "结果": "66", "单位": "umol/L"}]

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = export_rows_to_xlsx(rows, temp_dir, "sample")
            dataframe = pd.read_excel(output_path)

        self.assertEqual(list(dataframe.columns), ["项目名称", "结果", "单位"])
        self.assertEqual(dataframe.iloc[0].to_dict(), rows[0])
        self.assertTrue(output_path.endswith(".xlsx"))
        self.assertTrue(os.path.basename(output_path).startswith("sample"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_lab_report_extractor -v`
Expected: `FAIL` or `ERROR` because `lab_report_extractor.py` and the tested functions do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
# lab_report_extractor.py
import pandas as pd
from pathlib import Path


COLUMN_NAMES = ["项目名称", "结果", "单位"]


def normalize_extracted_items(items):
    cleaned = []
    seen = set()
    for item in items or []:
        row = {
            "项目名称": str(item.get("项目名称", "")).strip(),
            "结果": str(item.get("结果", "")).strip(),
            "单位": str(item.get("单位", "")).strip(),
        }
        if not row["项目名称"] or not row["结果"]:
            continue
        signature = (row["项目名称"], row["结果"], row["单位"])
        if signature in seen:
            continue
        seen.add(signature)
        cleaned.append(row)
    return cleaned


def export_rows_to_xlsx(rows, output_dir, stem):
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    output_path = target_dir / f"{stem}.xlsx"
    dataframe = pd.DataFrame(rows, columns=COLUMN_NAMES)
    dataframe.to_excel(output_path, index=False, engine="openpyxl")
    return str(output_path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_lab_report_extractor -v`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add tests/test_lab_report_extractor.py lab_report_extractor.py
git commit -m "test: cover lab report export helpers"
```

### Task 2: Add minimal file-to-image and vision extraction flow

**Files:**
- Modify: `lab_report_extractor.py`
- Test: `tests/test_lab_report_extractor.py`

- [ ] **Step 1: Write the failing test**

```python
class DocxImageExtractionTests(unittest.TestCase):
    def test_extract_first_image_bytes_rejects_docx_without_media(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            docx_path = os.path.join(temp_dir, "empty.docx")
            with zipfile.ZipFile(docx_path, "w") as archive:
                archive.writestr("[Content_Types].xml", "")

            with self.assertRaisesRegex(ValueError, "未发现可提取图片"):
                extract_first_image_payload(docx_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_lab_report_extractor -v`
Expected: `ERROR` because `extract_first_image_payload` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
import base64
import json
import mimetypes
import os
import zipfile
from openai import OpenAI


SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
SUPPORTED_FILE_SUFFIXES = SUPPORTED_IMAGE_SUFFIXES | {".docx"}
DEFAULT_VISION_MODEL = "qwen-vl-ocr-latest"


def extract_first_image_payload(file_path):
    suffix = Path(file_path).suffix.lower()
    if suffix in SUPPORTED_IMAGE_SUFFIXES:
        return _build_image_payload(file_path)
    if suffix != ".docx":
        raise ValueError("仅支持 .docx、.png、.jpg、.jpeg 文件。")

    with zipfile.ZipFile(file_path, "r") as archive:
        media_names = sorted(
            name for name in archive.namelist() if name.startswith("word/media/")
        )
        if not media_names:
            raise ValueError("文档中未发现可提取图片。")
        first_name = media_names[0]
        image_bytes = archive.read(first_name)
    mime_type, _ = mimetypes.guess_type(first_name)
    if not mime_type:
        mime_type = "image/png"
    data = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{data}"


def _build_image_payload(file_path):
    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type:
        mime_type = "image/png"
    with open(file_path, "rb") as handle:
        data = base64.b64encode(handle.read()).decode("utf-8")
    return f"data:{mime_type};base64,{data}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_lab_report_extractor -v`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add tests/test_lab_report_extractor.py lab_report_extractor.py
git commit -m "feat: add lab report image payload extraction"
```

### Task 3: Add the minimal DashScope extraction function and demo UI

**Files:**
- Modify: `lab_report_extractor.py`
- Create: `extract_demo.py`
- Test: `tests/test_lab_report_extractor.py`

- [ ] **Step 1: Write the failing test**

```python
class ParseModelResponseTests(unittest.TestCase):
    def test_parse_model_response_reads_json_inside_code_fence(self):
        content = """```json
{"items":[{"项目名称":"肌酐","结果":"66","单位":"umol/L"}]}
```"""

        rows = parse_model_response(content)

        self.assertEqual(rows, [{"项目名称": "肌酐", "结果": "66", "单位": "umol/L"}])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_lab_report_extractor -v`
Expected: `ERROR` because `parse_model_response` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
EXTRACTION_PROMPT = """
你将看到一张化验单图片。
只提取第一位患者的检验项目。
只返回 JSON，不要输出解释，不要输出 Markdown。
JSON 格式如下：
{"items":[{"项目名称":"","结果":"","单位":""}]}
要求：
1. 只保留项目名称、结果、单位三列。
2. 如果单位缺失，单位填空字符串。
3. 不要捏造图片中不存在的内容。
4. 若识别不到有效项目，返回 {"items":[]}
""".strip()


def get_vision_client():
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError("Missing DASHSCOPE_API_KEY. Set it in your environment or Hugging Face Space secrets.")
    return OpenAI(api_key=api_key, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")


def parse_model_response(content):
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
        cleaned = cleaned.rsplit("```", 1)[0]
    payload = json.loads(cleaned)
    return normalize_extracted_items(payload.get("items", []))


def extract_lab_items_from_file(file_path, client=None, model=DEFAULT_VISION_MODEL):
    image_payload = extract_first_image_payload(file_path)
    vision_client = client or get_vision_client()
    completion = vision_client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": EXTRACTION_PROMPT},
                    {"type": "image_url", "image_url": {"url": image_payload}},
                ],
            }
        ],
    )
    content = completion.choices[0].message.content
    rows = parse_model_response(content)
    if not rows:
        raise ValueError("未识别到有效化验项目。")
    return rows
```

```python
# extract_demo.py
import tempfile

import gradio as gr
import pandas as pd

from lab_report_extractor import extract_lab_items_from_file, export_rows_to_xlsx


def run_extraction(file_path):
    rows = extract_lab_items_from_file(file_path)
    output_path = export_rows_to_xlsx(rows, tempfile.gettempdir(), "lab_extract_result")
    return "提取完成", pd.DataFrame(rows), output_path


with gr.Blocks(title="化验单提取演示") as demo:
    gr.Markdown("## 化验单提取演示")
    file_input = gr.File(label="上传 .docx 或图片", type="filepath", file_types=[".docx", ".png", ".jpg", ".jpeg"])
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_lab_report_extractor -v`
Expected: `OK`

Run: `python -c "import extract_demo"`
Expected: command exits without traceback

- [ ] **Step 5: Commit**

```bash
git add tests/test_lab_report_extractor.py lab_report_extractor.py extract_demo.py
git commit -m "feat: add lab report extraction demo"
```
