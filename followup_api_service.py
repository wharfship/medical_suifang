"""Session-scoped business workflow for the HTTP API.

This module intentionally does not import Gradio. It preserves the existing
follow-up rules while keeping one tracker and conversation per API session.
"""

from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable

import pandas as pd

from Model_initialization import generate_question, parse_answer
from excel_adjusting import format_excel
from field_rules import apply_field_completion_rules
from lab_report_extractor import extract_followup_value_from_rows, extract_lab_items_from_file
from medical_output_flow import OUTPUT_DIR, persist_followup_export, update_patient_summary_workbook
from state_tracking import FieldStateTracker
from statistic_preprocessing import load_excel_template
from workflow_status import (
    finalize_after_attempt_limit,
    get_field_attempt_limit,
    is_final_status,
    normalize_parse_result,
)


BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = BASE_DIR / "人工智能供者随访计划.xls"
ALLOWED_REPORT_SUFFIXES = {".docx", ".png", ".jpg", ".jpeg"}
MAX_REPORT_SIZE_BYTES = 20 * 1024 * 1024
KIDNEY_ULTRASOUND_FIELD = "肾脏彩超"
UPLOAD_TRIGGER_KEYWORDS = ("化验", "检查", "血生化", "肌酐", "尿常规", "肾脏", "报告")
UPLOAD_REVEAL_REMAINING_FIELDS = 6
UPLOAD_REVEAL_PROGRESS = 0.72
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
COLUMN_NAMES = {
    "field": "填写内容",
    "value": "填写数据",
    "evidence": "数据原始依据",
}


class FollowupError(Exception):
    """Base error that can be returned safely to API callers."""


class FollowupNotFoundError(FollowupError):
    pass


class FollowupValidationError(FollowupError):
    pass


class AlgorithmServiceError(FollowupError):
    pass


class FollowupStorageError(FollowupError):
    pass


@dataclass
class FollowupSession:
    followup_id: str
    patient_name: str
    student_id: str
    followup_date: str
    metadata: dict
    tracker: FieldStateTracker
    field_attempts: dict[str, int] = field(default_factory=dict)
    messages: list[dict[str, str]] = field(default_factory=list)
    current_question: str | None = None
    persisted: bool = False
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)


class FollowupWorkflow:
    """Runs one independent follow-up workflow per in-memory session."""

    def __init__(self, metadata_factory: Callable[[], dict] | None = None, output_dir: Path | None = None):
        self._metadata_factory = metadata_factory or self._load_default_metadata
        self._output_dir = Path(output_dir or OUTPUT_DIR)
        self._sessions: dict[str, FollowupSession] = {}
        self._sessions_lock = threading.RLock()

    @staticmethod
    def _load_default_metadata():
        if not TEMPLATE_PATH.exists():
            raise RuntimeError(f"Excel template not found: {TEMPLATE_PATH}")
        return load_excel_template(TEMPLATE_PATH)

    def create_followup(self, patient_name: str, student_id: str):
        patient_name = self._validate_patient_name(patient_name)
        student_id = self._validate_student_id(student_id)
        metadata = self._metadata_factory()
        session = FollowupSession(
            followup_id=str(uuid.uuid4()),
            patient_name=patient_name,
            student_id=student_id,
            followup_date=date.today().strftime("%Y.%m.%d"),
            metadata=metadata,
            tracker=FieldStateTracker(metadata),
        )

        self._add_message(session, "assistant", "您好，我是医疗随访助手，需要了解您的健康状况。")
        field_name = self._finalize_computed_fields(session)
        if field_name:
            self._ask_next_question(session, field_name)

        with self._sessions_lock:
            self._sessions[session.followup_id] = session
        return self._build_view(session)

    def get_followup(self, followup_id: str):
        session = self._get_session(followup_id)
        with session.lock:
            self._persist_if_finished(session)
            return self._build_view(session)

    def submit_message(self, followup_id: str, content: str):
        message = str(content or "").strip()
        if not message:
            raise FollowupValidationError("回答内容不能为空。")

        session = self._get_session(followup_id)
        with session.lock:
            field_name = session.tracker.get_next_field()
            if field_name is None:
                raise FollowupValidationError("本次随访已完成，不能继续提交回答。")

            try:
                raw_result = parse_answer(
                    field_name,
                    message,
                    session.metadata[field_name]["描述"],
                    session.tracker.get_dialogue_history(),
                )
            except Exception as exc:
                raise AlgorithmServiceError("回答解析服务暂不可用，请稍后重试。") from exc

            raw_result["field"] = field_name
            result = apply_field_completion_rules(field_name, normalize_parse_result(raw_result))
            self._add_message(session, "user", message)
            result = self._advance_after_parse(session, field_name, result)
            self._persist_if_finished(session)
            return {"parsed_result": result, **self._build_view(session)}

    def submit_report(self, followup_id: str, filename: str, content: bytes):
        session = self._get_session(followup_id)
        with session.lock:
            field_name = session.tracker.get_next_field()
            if field_name is None:
                raise FollowupValidationError("本次随访已完成，不能继续上传文件。")

            self._validate_report(filename, content)
            if field_name == KIDNEY_ULTRASOUND_FIELD:
                rows = []
            else:
                rows = self._extract_lab_rows(filename, content)

            result = self._build_upload_result(field_name, rows)
            session.tracker.update_field(field_name, result)
            session.field_attempts.pop(field_name, None)
            self._add_message(session, "assistant", self._build_confirmation_message(field_name, result))

            next_field = self._finalize_computed_fields(session)
            if next_field:
                self._ask_next_question(session, next_field)
            else:
                session.current_question = None

            self._persist_if_finished(session)
            return {"rows": rows, "parsed_result": result, **self._build_view(session)}

    def _advance_after_parse(self, session: FollowupSession, field_name: str, result: dict):
        status_for_question = None
        field_finished = is_final_status(result["status"])

        if result["status"] == "ask_again":
            session.field_attempts[field_name] = session.field_attempts.get(field_name, 0) + 1
            if session.field_attempts[field_name] >= get_field_attempt_limit(session.metadata, field_name):
                result = finalize_after_attempt_limit(result)
                session.tracker.update_field(field_name, result)
                session.field_attempts.pop(field_name, None)
                self._add_message(session, "assistant", self._build_confirmation_message(field_name, result))
                field_finished = True
            else:
                status_for_question = "ask_again"
                field_finished = False
        else:
            session.tracker.update_field(field_name, result)
            session.field_attempts.pop(field_name, None)
            self._add_message(session, "assistant", self._build_confirmation_message(field_name, result))

        next_field = self._finalize_computed_fields(session) if field_finished else session.tracker.get_next_field()
        if next_field:
            self._ask_next_question(session, next_field, status_for_question or "first_ask")
        else:
            session.current_question = None
        return result

    def _ask_next_question(self, session: FollowupSession, field_name: str, status: str = "first_ask"):
        try:
            question = generate_question(
                field_name,
                session.metadata,
                session.tracker.get_dialogue_history(),
                status,
            )
        except Exception as exc:
            raise AlgorithmServiceError("提问生成服务暂不可用，请稍后重试。") from exc
        session.current_question = question
        self._add_message(session, "assistant", question)

    def _finalize_computed_fields(self, session: FollowupSession):
        while True:
            field_name = session.tracker.get_next_field()
            if field_name == "BMI":
                result = self._build_bmi_result(session)
                evidence = "由当前身高和当前体重自动计算"
            elif field_name in COMPUTED_SUMMARY_FIELDS:
                result = self._build_summary_result(session, field_name)
                evidence = result["evidence"]
            else:
                return field_name

            session.tracker.update_field(field_name, result, evidence)
            self._add_message(session, "assistant", self._build_confirmation_message(field_name, result))

    @staticmethod
    def _build_upload_result(field_name: str, rows: list[dict]):
        if field_name == KIDNEY_ULTRASOUND_FIELD:
            return {
                "status": "done",
                "completion": "complete",
                "field_value": "已上传肾脏彩超",
                "confidence": 1.0,
                "reasoning": "用户已上传肾脏彩超图片。",
                "evidence": "patient: 已上传肾脏彩超图片。",
            }

        extracted_value = extract_followup_value_from_rows(field_name, rows)
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

    @staticmethod
    def _build_confirmation_message(field_name: str, result: dict):
        value = result.get("field_value", "")
        confidence = result.get("confidence", 0.0)
        if result.get("status") == "later":
            return "好的，这项我先记为待补充，您后续提供资料后再完善。"
        if result.get("status") == "manual_review":
            return "这项信息我先标记为需人工复核，后续再处理。"
        if result.get("completion") == "complete" and value:
            return f"已记录: {field_name} = {value} (置信度: {confidence:.2f})"
        if result.get("completion") == "partial":
            return f"已记录目前能确认的部分信息: {field_name} = {value}" if value else "这项我先按部分信息收口，后续如有资料可再补充。"
        return "好的，这项先记为暂未获取。"

    @staticmethod
    def _build_bmi_result(session: FollowupSession):
        height_cm = FollowupWorkflow._extract_number(session.tracker.get_field_value("当前身高"))
        weight_kg = FollowupWorkflow._extract_number(session.tracker.get_field_value("当前体重"))
        if not height_cm or not weight_kg:
            return {
                "status": "done",
                "completion": "empty",
                "field_value": "",
                "confidence": 1.0,
                "reasoning": "缺少可用的身高或体重，无法计算 BMI。",
                "evidence": "AI: BMI 由当前身高与当前体重自动计算；当前缺少至少一项有效数值。",
            }
        bmi = round(weight_kg / ((height_cm / 100) ** 2), 2)
        return {
            "status": "done",
            "completion": "complete",
            "field_value": str(bmi),
            "confidence": 1.0,
            "reasoning": "根据当前身高和当前体重自动计算 BMI。",
            "evidence": f"AI: BMI 由系统自动计算。 patient: 当前身高={height_cm}cm, 当前体重={weight_kg}kg。",
        }

    @staticmethod
    def _build_summary_result(session: FollowupSession, field_name: str):
        parts = COMPUTED_SUMMARY_FIELDS[field_name]
        value = "；".join(
            f"{label}：{session.tracker.get_field_value(child) or ''}" for label, child in parts
        )
        evidence = "\n".join(
            session.tracker.filled_data.get(child, {}).get("evidence", "")
            for _, child in parts
            if session.tracker.filled_data.get(child, {}).get("evidence", "")
        )
        return {
            "status": "done",
            "completion": "complete",
            "field_value": value,
            "confidence": 1.0,
            "reasoning": f"根据已完成的子字段自动汇总 {field_name}。",
            "evidence": evidence,
        }

    @staticmethod
    def _extract_number(value):
        match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
        return float(match.group()) if match else None

    @staticmethod
    def _add_message(session: FollowupSession, role: str, content: str):
        session.messages.append({"role": role, "content": content})
        session.tracker.add_dialogue("AI" if role == "assistant" else "Patient", content)

    @staticmethod
    def _validate_patient_name(patient_name: str):
        normalized = re.sub(r"\s+", " ", str(patient_name or "").replace("\u3000", " ").strip())
        if not normalized:
            raise FollowupValidationError("请输入患者姓名。")
        if not 2 <= len(normalized) <= 20:
            raise FollowupValidationError("姓名长度需为2到20个字符。")
        if normalized.isdigit() or not re.fullmatch(r"[A-Za-z\u4e00-\u9fff· ]+", normalized):
            raise FollowupValidationError("姓名格式不正确。")
        return normalized

    @staticmethod
    def _validate_student_id(student_id: str):
        normalized = str(student_id or "").strip()
        if not re.fullmatch(r"\d{8}", normalized):
            raise FollowupValidationError("学工号必须为8位数字。")
        return normalized

    @staticmethod
    def _validate_report(filename: str, content: bytes):
        suffix = Path(filename or "").suffix.lower()
        if suffix not in ALLOWED_REPORT_SUFFIXES:
            raise FollowupValidationError("仅支持 .docx、.png、.jpg、.jpeg 格式的化验单。")
        if not content:
            raise FollowupValidationError("上传文件不能为空。")
        if len(content) > MAX_REPORT_SIZE_BYTES:
            raise FollowupValidationError("上传文件不能超过20MB。")

    @staticmethod
    def _extract_lab_rows(filename: str, content: bytes):
        suffix = Path(filename).suffix.lower()
        temporary_path = BASE_DIR / f".upload_{uuid.uuid4().hex}{suffix}"
        temporary_path.write_bytes(content)
        try:
            return extract_lab_items_from_file(str(temporary_path))
        except Exception as exc:
            raise AlgorithmServiceError("化验单识别失败，请确认文件清晰且格式正确后重试。") from exc
        finally:
            temporary_path.unlink(missing_ok=True)

    def _persist_if_finished(self, session: FollowupSession):
        if session.persisted or session.tracker.get_next_field() is not None:
            return

        source_excel = None
        try:
            source_excel = self._write_result_workbook(session)
            persist_followup_export(
                source_excel,
                output_dir=self._output_dir,
                patient_name=session.patient_name,
                student_id=session.student_id,
                followup_date=session.followup_date,
                followup_label=datetime.now().strftime("%Y/%m/%d/%H:%M随访"),
            )
            try:
                update_patient_summary_workbook(
                    output_dir=self._output_dir,
                    patient_name=session.patient_name,
                    student_id=session.student_id,
                )
            except Exception:
                pass
        except Exception as exc:
            raise FollowupStorageError("随访结果保存失败，请稍后重试。") from exc
        finally:
            if source_excel is not None:
                source_excel.unlink(missing_ok=True)
                source_excel.parent.rmdir()

        session.persisted = True

    def _write_result_workbook(self, session: FollowupSession):
        dataframe = pd.DataFrame(session.tracker.get_parse_history())
        dataframe = self._filter_exported_child_rows(dataframe)
        dataframe = dataframe.rename(columns=COLUMN_NAMES)
        temporary_dir = self._output_dir / "_api_tmp" / session.followup_id
        temporary_dir.mkdir(parents=True, exist_ok=True)
        workbook_path = temporary_dir / "medical_data.xlsx"
        dataframe.to_excel(workbook_path, index=False, engine="openpyxl")
        format_excel(workbook_path, workbook_path)
        return workbook_path

    @staticmethod
    def _filter_exported_child_rows(dataframe):
        if dataframe.empty or "field" not in dataframe.columns:
            return dataframe
        completed_fields = set(dataframe["field"].tolist())
        hidden_child_fields = {
            child_field
            for parent_field, parts in COMPUTED_SUMMARY_FIELDS.items()
            if parent_field in completed_fields
            for _, child_field in parts
        }
        if not hidden_child_fields:
            return dataframe
        return dataframe[~dataframe["field"].isin(hidden_child_fields)].reset_index(drop=True)

    def _get_session(self, followup_id: str):
        with self._sessions_lock:
            session = self._sessions.get(followup_id)
        if session is None:
            raise FollowupNotFoundError("随访会话不存在或已因服务重启失效。")
        return session

    def _build_view(self, session: FollowupSession):
        field_name = session.tracker.get_next_field()
        progress = self._get_progress(session)
        return {
            "followup_id": session.followup_id,
            "status": "finished" if field_name is None else "in_progress",
            "patient_name": session.patient_name,
            "student_id": session.student_id,
            "progress": progress,
            "current_field": {"label": field_name} if field_name else None,
            "question": session.current_question,
            "messages": list(session.messages),
            "upload_available": self._should_offer_upload(field_name, progress),
            "accepted_report_types": sorted(ALLOWED_REPORT_SUFFIXES),
        }

    def _get_progress(self, session: FollowupSession):
        cache: dict[str, str] = {}
        completed = 0
        inactive = 0
        for field_name in session.metadata:
            state = self._resolve_field_state(session, field_name, cache)
            completed += state == "completed"
            inactive += state == "inactive"
        total = max(len(session.metadata) - inactive, 0)
        return {
            "completed": completed,
            "total": total,
            "inactive": inactive,
            "percent": 100 if total == 0 else round((completed / total) * 100),
        }

    def _resolve_field_state(self, session: FollowupSession, field_name: str, cache: dict[str, str]):
        if field_name in cache:
            return cache[field_name]
        if field_name in session.tracker.filled_data:
            cache[field_name] = "completed"
            return cache[field_name]
        dependencies = session.metadata[field_name].get("依赖")
        if not dependencies:
            cache[field_name] = "pending"
            return cache[field_name]
        parent = dependencies.get("parent")
        if not parent or parent not in session.metadata:
            cache[field_name] = "pending"
            return cache[field_name]
        if self._resolve_field_state(session, parent, cache) == "inactive":
            cache[field_name] = "inactive"
            return cache[field_name]
        if parent not in session.tracker.filled_data:
            cache[field_name] = "pending"
            return cache[field_name]
        parent_value = session.tracker.filled_data[parent]["value"]
        condition = dependencies.get("condition")
        opposite_condition = dependencies.get("opposite_condition")
        if condition is not None:
            allowed = condition if isinstance(condition, list) else [condition]
            cache[field_name] = "pending" if parent_value in allowed else "inactive"
        elif opposite_condition is not None:
            blocked = opposite_condition if isinstance(opposite_condition, list) else [opposite_condition]
            cache[field_name] = "inactive" if parent_value in blocked else "pending"
        else:
            cache[field_name] = "pending"
        return cache[field_name]

    @staticmethod
    def _should_offer_upload(field_name: str | None, progress: dict):
        if field_name is None or progress["total"] == 0:
            return True
        if progress["total"] - progress["completed"] <= UPLOAD_REVEAL_REMAINING_FIELDS:
            return True
        if any(keyword in field_name for keyword in UPLOAD_TRIGGER_KEYWORDS):
            return True
        return (progress["completed"] / progress["total"]) >= UPLOAD_REVEAL_PROGRESS
