import base64
import json
import mimetypes
import os
import re
import tempfile
import zipfile
from pathlib import Path

import pandas as pd
from openai import OpenAI


DISPLAY_COLUMNS = ["项目名称", "结果", "单位"]
DEFAULT_VISION_MODEL = "qwen-vl-ocr-latest"
LEGACY_WORD_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
WORD_FORMAT_XML_DOCUMENT = 16
SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}

RESULT_ABBREVIATION_PATTERN = re.compile(r"^[A-Z][A-Z0-9/\-]{1,12}$")
RESULT_VALUE_PATTERN = re.compile(r"[0-9]|阴性|阳性|正常|异常|未见|<|>|↑|↓")
UNIT_LIKE_PATTERN = re.compile(
    r"^(?:"
    r"[A-Za-zμuU%]+/[A-Za-zμuU%]+"
    r"|mmol/L"
    r"|umol/L"
    r"|mg/L"
    r"|g/L"
    r"|U/L"
    r"|IU/L"
    r"|KU/L"
    r"|ng/L"
    r"|ng/mL"
    r"|mosm/L"
    r"|%"
    r")$"
)

EXTRACTION_PROMPT = """
You will receive an image of a lab report. Extract only the first patient's rows.

The table has five columns:
1. Chinese item name
2. English abbreviation
3. Actual result
4. Unit
5. Reference range

Return JSON only:
{"items":[{"item_name":"","abbr":"","result":"","unit":"","reference_range":""}]}

Rules:
1. Copy all five columns for every visible row.
2. `item_name` = column 1 Chinese name.
3. `abbr` = column 2 English abbreviation.
4. `result` = column 3 actual result only.
5. `unit` = column 4 unit only.
6. `reference_range` = column 5 reference range only.
7. Do not move column 2 or column 4 into `result`.
8. If no valid rows are visible, return {"items":[]}.
""".strip()

RETRY_EXTRACTION_PROMPT = """
Your previous extraction used the wrong column for `result`.
Retry the same image and copy all five columns again.

The correct row structure is:
Chinese item name | English abbreviation | Actual result | Unit | Reference range

Return JSON only:
{"items":[{"item_name":"","abbr":"","result":"","unit":"","reference_range":""}]}

Critical rules:
1. `result` must be copied from column 3 only.
2. `abbr` must be copied from column 2 only.
3. `unit` must be copied from column 4 only.
4. Values like ALP, GGT, TP, ALB, Na, K, Cl, CO2, AFP belong in `abbr`, not `result`.
5. Values like U/L, g/L, mmol/L, umol/L, KU/L, ng/L, ng/mL belong in `unit`, not `result`.
6. `result` should usually be a number or a real outcome such as 阴性, 阳性, 正常, 异常, 未见.
""".strip()


def build_display_rows(rows):
    return [
        {
            "项目名称": row["item_name"],
            "结果": row["result"],
            "单位": row["unit"],
        }
        for row in rows
    ]


def normalize_extracted_items(items):
    cleaned = []
    seen = set()
    for item in items or []:
        row = {
            "item_name": str(item.get("item_name", "")).strip(),
            "abbr": str(item.get("abbr", "")).strip(),
            "result": str(item.get("result", "")).strip(),
            "unit": str(item.get("unit", "")).strip(),
            "reference_range": str(item.get("reference_range", "")).strip(),
        }
        if not row["item_name"] or not row["result"]:
            continue
        signature = tuple(row.values())
        if signature in seen:
            continue
        seen.add(signature)
        cleaned.append(row)
    return cleaned


def export_rows_to_xlsx(rows, output_dir, stem):
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    output_path = target_dir / f"{stem}.xlsx"
    dataframe = pd.DataFrame(build_display_rows(rows), columns=DISPLAY_COLUMNS)
    dataframe.to_excel(output_path, index=False, engine="openpyxl")
    return str(output_path)


def _build_image_payload(file_path):
    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type:
        mime_type = "image/png"
    with open(file_path, "rb") as handle:
        data = base64.b64encode(handle.read()).decode("utf-8")
    return f"data:{mime_type};base64,{data}"


def is_legacy_word_binary(file_path):
    with open(file_path, "rb") as handle:
        return handle.read(len(LEGACY_WORD_SIGNATURE)) == LEGACY_WORD_SIGNATURE


def convert_legacy_word_to_docx(file_path):
    try:
        import win32com.client  # type: ignore
    except ImportError as exc:
        raise ValueError("检测到这是老式 Word 二进制文档，需要安装 pywin32 才能自动转换。") from exc

    target_dir = Path(tempfile.mkdtemp(prefix="legacy_word_"))
    output_path = target_dir / f"{Path(file_path).stem}_converted.docx"

    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    document = None
    try:
        document = word.Documents.Open(str(Path(file_path).resolve()))
        document.SaveAs(str(output_path), FileFormat=WORD_FORMAT_XML_DOCUMENT)
    except Exception as exc:
        raise ValueError(f"老式 Word 文档转换失败：{exc}") from exc
    finally:
        if document is not None:
            document.Close(False)
        word.Quit()

    return str(output_path)


def _find_first_media_file(archive):
    media_names = sorted(
        name
        for name in archive.namelist()
        if name.startswith("word/media/") and not name.endswith("/")
    )
    for name in media_names:
        image_bytes = archive.read(name)
        if image_bytes:
            return name, image_bytes
    raise ValueError("docx 文档中未发现可提取图片。")


def _read_docx_first_image_bytes(file_path):
    actual_path = str(file_path)
    if not zipfile.is_zipfile(actual_path):
        if is_legacy_word_binary(actual_path):
            actual_path = convert_legacy_word_to_docx(actual_path)
        else:
            raise ValueError("上传文件后缀是 .docx，但文件内容不是有效的 docx 压缩包。")

    with zipfile.ZipFile(actual_path, "r") as archive:
        return _find_first_media_file(archive)


def extract_first_image_payload(file_path):
    file_path = str(file_path)
    suffix = Path(file_path).suffix.lower()
    if suffix in SUPPORTED_IMAGE_SUFFIXES:
        return _build_image_payload(file_path)
    if suffix != ".docx":
        raise ValueError("仅支持 .docx、.png、.jpg、.jpeg 文件。")

    first_name, image_bytes = _read_docx_first_image_bytes(file_path)
    mime_type, _ = mimetypes.guess_type(first_name)
    if not mime_type:
        mime_type = "image/png"
    data = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{data}"


def get_vision_client():
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing DASHSCOPE_API_KEY. Set it in your environment or Hugging Face Space secrets."
        )
    return OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )


def parse_model_response(content):
    cleaned = str(content or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
        cleaned = cleaned.rsplit("```", 1)[0]
    payload = json.loads(cleaned)
    return normalize_extracted_items(payload.get("items", []))


def _call_extraction_model(vision_client, model, image_payload, prompt):
    completion = vision_client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_payload}},
                ],
            }
        ],
    )
    return parse_model_response(completion.choices[0].message.content)


def _looks_like_result_abbreviation(value):
    text = str(value or "").strip()
    if not text:
        return False
    if RESULT_VALUE_PATTERN.search(text):
        return False
    return bool(RESULT_ABBREVIATION_PATTERN.fullmatch(text))


def _looks_like_unit_value(value):
    text = str(value or "").strip()
    if not text:
        return False
    return bool(UNIT_LIKE_PATTERN.fullmatch(text))


def should_retry_for_result_column(rows):
    if not rows:
        return False

    threshold = max(1, len(rows) // 2)
    abbreviation_like_count = sum(
        1
        for row in rows
        if row.get("result", "").strip() == row.get("abbr", "").strip()
        or _looks_like_result_abbreviation(row.get("result", ""))
    )
    unit_like_count = sum(
        1
        for row in rows
        if row.get("result", "").strip() == row.get("unit", "").strip()
        or _looks_like_unit_value(row.get("result", ""))
    )

    return (abbreviation_like_count >= threshold and abbreviation_like_count > 0) or (
        unit_like_count >= threshold and unit_like_count > 0
    )


def extract_lab_items_from_file(file_path, client=None, model=DEFAULT_VISION_MODEL):
    image_payload = extract_first_image_payload(file_path)
    vision_client = client or get_vision_client()

    rows = _call_extraction_model(vision_client, model, image_payload, EXTRACTION_PROMPT)
    if should_retry_for_result_column(rows):
        retried_rows = _call_extraction_model(
            vision_client,
            model,
            image_payload,
            RETRY_EXTRACTION_PROMPT,
        )
        if retried_rows:
            rows = retried_rows

    if not rows:
        raise ValueError("未识别到有效化验项目。")
    return rows
