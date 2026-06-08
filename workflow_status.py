CANONICAL_STATUSES = {"done", "ask_again", "later", "manual_review"}
COMPLETION_LEVELS = {"complete", "partial", "empty"}
HOSPITAL_CHECK_GATE_FIELD = "请问您最近有去医院进行检查吗？"

LEGACY_STATUS_MAPPING = {
    "success": ("done", "complete"),
    "partial_success": ("ask_again", "partial"),
    "ambiguous": ("ask_again", "empty"),
    "skip": ("done", "empty"),
    "pending": ("later", "empty"),
    "escalate": ("manual_review", "partial"),
}


def clamp_confidence(value):
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric_value))


def normalize_gate_field_value(field, value):
    text = str(value or "").strip()
    if field != HOSPITAL_CHECK_GATE_FIELD or not text:
        return text

    if any(token in text for token in ("不知", "不清楚", "记不清", "忘了", "不确定", "说不清")):
        return "未知"
    if any(token in text for token in ("没去", "没有去", "没查", "没有查", "没做检查", "没有做检查", "未检查", "没复查", "没有复查")):
        return "否"
    if any(token in text for token in ("去过", "查过", "检查过", "做过检查", "复查过", "去医院查了", "去医院做了")):
        return "是"
    if text in {"是", "否", "未知"}:
        return text
    return text


def infer_completion(status, field_value):
    has_value = bool(str(field_value or "").strip())
    if status == "done":
        return "complete" if has_value else "empty"
    if status in {"later", "manual_review"}:
        return "partial" if has_value else "empty"
    return "partial" if has_value else "empty"


def normalize_parse_result(raw_result):
    result = dict(raw_result or {})
    raw_status = str(result.get("status", "") or "").strip()
    raw_completion = str(result.get("completion", "") or "").strip()
    field = str(result.get("field", "") or "").strip()
    field_value = normalize_gate_field_value(field, str(result.get("field_value", "") or "").strip())
    reasoning = str(result.get("reasoning", "") or "").strip()
    evidence = str(result.get("evidence", "") or "").strip()

    if raw_status in LEGACY_STATUS_MAPPING:
        status, legacy_completion = LEGACY_STATUS_MAPPING[raw_status]
        if not raw_completion:
            raw_completion = legacy_completion
    elif raw_status in CANONICAL_STATUSES:
        status = raw_status
    else:
        status = "ask_again"

    if raw_completion in COMPLETION_LEVELS:
        completion = raw_completion
    else:
        completion = infer_completion(status, field_value)

    if status == "ask_again" and completion == "complete":
        status = "done"

    if status == "later" and completion == "complete":
        status = "done"

    if status == "done" and not field_value and completion == "complete":
        completion = "empty"

    return {
        "status": status,
        "completion": completion,
        "field_value": field_value,
        "confidence": clamp_confidence(result.get("confidence")),
        "reasoning": reasoning,
        "evidence": evidence,
    }


def is_final_status(status):
    return status in {"done", "later", "manual_review"}


def get_field_attempt_limit(metadata, field, default=2):
    field_meta = metadata.get(field, {})
    raw_limit = field_meta.get("追问上限", default)
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return default
    return max(1, limit)


def finalize_after_attempt_limit(result):
    finalized = dict(result)
    finalized["status"] = "done"
    if finalized.get("completion") not in {"complete", "partial"}:
        finalized["completion"] = "empty"

    note = "已达到追问上限，先结束当前字段。"
    reasoning = finalized.get("reasoning", "")
    finalized["reasoning"] = f"{reasoning} {note}".strip()
    return finalized
