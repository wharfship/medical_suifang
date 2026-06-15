import re

# 这些字段规则来自你现有的医院表单逻辑，并参考了“真实对话记录表.xlsx”里的样本。
# 目标不是替代模型，而是给模型结果加一层稳定的“填表口径校正”。

YES_NO_FIELDS = {
    "当前有无糖尿病",
    "当前有无高血压",
    "是否曾患冠心病",
    "是否曾患脑血管病",
    "请问您最近有去医院进行检查吗？",
    "近一年是否存在手术切口疼痛",
    "（若有高血压）是否为过去一年新发",
    "（若有糖尿病）是否为过去一年新发",
    "（若曾患冠心病）是否为过去一年新发",
    "（若曾患脑血管病）是否为过去一年新发",
    "（若无高血压）过去一年有无出现血压升高",
    "（若无糖尿病）过去一年有无出现空腹血糖升高",
}

HEIGHT_FIELDS = {"当前身高"}
WEIGHT_FIELDS = {"当前体重"}
BLOOD_PRESSURE_FIELDS = {"当前血压", "（若有高血压）最高达"}
NUMERIC_FIELDS = {
    "当前空腹血糖": "mmol/L",
    "（若有糖尿病）最高达": "mmol/L",
    "（若有糖尿病）糖化血红蛋白": "%",
    "血生化：血清肌酐": "umol/L",
    "随访时受者状态": "umol/L",
}
DURATION_FIELDS = {
    "（若有高血压）发现高血压至今时间",
    "（若有糖尿病）发现糖尿病至今时间",
    "（若曾患冠心病）罹患冠心病至今时间",
    "（若曾患脑血管病）罹患脑血管病至今时间",
    "（若存在手术切口疼痛）手术切口疼痛持续时间",
}
PAIN_SCORE_FIELDS = {"（若存在手术切口疼痛）疼痛程度评分"}
TEXT_COMPLETE_FIELDS = {
    "其余病史及用药情况",
    "尿常规：尿蛋白、尿潜血",
    "肾脏彩超",
}

STRICT_COMPLEX_FIELDS = {
    "（若有高血压）药物控制方案",
    "（若有糖尿病）药物控制方案",
    "（若曾患冠心病）治疗方式",
    "（若曾患脑血管病）具体疾病、治疗方式及有无后遗症",
    "（若有其余病史）请描述具体疾病、治疗方式、用药种类、用法、治疗效果",
}

FIELD_RULES = {
    "当前身高": {
        "minimum_requirement": "能提取出一个大致身高数值即可，医院表单可接受近似值。",
        "accepted_examples": ["1.64米", "164cm", "170多"],
        "followup_focus": "只在完全没有数值时再追问。",
    },
    "当前体重": {
        "minimum_requirement": "能提取出一个大致体重数值即可，可把斤换算成 kg。",
        "accepted_examples": ["150多斤", "75kg", "132斤"],
        "followup_focus": "只在完全没有体重数值时再追问。",
    },
    "当前血压": {
        "minimum_requirement": "至少能落下一组血压值，范围值也可接受。",
        "accepted_examples": ["120/80mmHg", "110-120/80-90mmHg"],
        "followup_focus": "如果已有一组可用血压值，不再追问更精确时间。",
    },
    "当前空腹血糖": {
        "minimum_requirement": "有一个可识别的空腹血糖数值即可。",
        "accepted_examples": ["5.6", "6.1mmol/L"],
        "followup_focus": "没有数值时才继续问。",
    },


    "（若有高血压）药物使用情况": {
        "minimum_requirement": "需要问到用药方案、规格以及服用频率。",
        "accepted_examples": ["吃硝苯地平，一次三片，想起来就吃", "吃降压药，具体剂量记不清"],
        "followup_focus": "患者没有明确回答问题时才继续追问",
    },
    "（若有糖尿病）药物使用情况": {
        "minimum_requirement": "需要问到用药方案、规格以及服用频率。",
        "accepted_examples": ["口服二甲双胍，规格是：500mg，每天两次", "打胰岛素，血糖控制还可以"],
        "followup_focus": "患者没有回答问题时才继续追问",
    },
    "（若曾患冠心病）药物使用情况": {
        "minimum_requirement": "需要问到用药方案、规格以及服用频率。",
        "accepted_examples": ["口服二甲双胍，500mg，每天两次", "打胰岛素，血糖控制还可以"],
        "followup_focus": "患者没有明确回答问题时才继续追问",
    },



    "（若有高血压）药物控制方案": {
        "minimum_requirement": "知道大致用药方案或控制情况即可，不强求剂量非常精确。",
        "accepted_examples": ["口服硝苯地平，血压基本稳定", "吃降压药，具体剂量记不清"],
        "followup_focus": "优先补药物名称、频次或控制情况三者里最缺的一项。",
    },
    "（若有糖尿病）药物控制方案": {
        "minimum_requirement": "知道大致用药方案或控制情况即可。",
        "accepted_examples": ["口服二甲双胍", "打胰岛素，血糖控制还可以"],
        "followup_focus": "优先补最核心的药物或控制情况。",
    },
    "其余病史及用药情况": {
        "minimum_requirement": "患者明确回答了已诊断出的具体疾病才可填写疾病名，如果患者只说症状或特征，按无病史处理填写“无”即可；",
        "accepted_examples": ["无", "腰间盘突出", "脑梗"],
        "followup_focus": "若只回答“有”但没说具体病名，才继续追问是什么具体疾病;如果识别到“咳嗽、头疼、发烧、难受”这类症状词,不要当成有效病史，继续追问或按无病史(填写“无”)处理",
    },

    "近一年是否存在手术切口疼痛": {
        "minimum_requirement": "只要能判断有/无/未知即可。",
        "accepted_examples": ["无", "有", "记不清"],
        "followup_focus": "这是是/否字段，不展开追问细节。",
    },
    "（若存在手术切口疼痛）手术切口疼痛持续时间": {
        "minimum_requirement": "医院表单接受模糊时长描述，如“术后至今”“间断出现”。",
        "accepted_examples": ["术后至今", "间断出现", "去年冬天有过一两次"],
        "followup_focus": "不强求精确到天。",
    },
    "（若存在手术切口疼痛）疼痛程度评分": {
        "minimum_requirement": "有一个 1-10 的大致疼痛评分即可。",
        "accepted_examples": ["3分", "8分", "大概4分"],
        "followup_focus": "只在没有任何评分时才追问。",
    },
    "血生化：血清肌酐": {
        "minimum_requirement": "有一个可写入表格的肌酐数值即可。",
        "accepted_examples": ["66", "120左右"],
        "followup_focus": "先要到一个大致数值，不强求化验时间。",
    },
    "尿常规：尿蛋白、尿潜血": {
        "minimum_requirement": "能判断阴性/阳性，或选择上传化验单结果即可。",
        "accepted_examples": ["阴性", "没有尿蛋白和尿潜血", "正常"],
        "followup_focus": "优先确认是否异常。",
    },
    "肾脏彩超": {
        "minimum_requirement": "能判断正常/异常，或选择上传化验单结果即可。",
        "accepted_examples": ["正常", "没事", "有囊肿"],
        "followup_focus": "不追问影像学细节。",
    },
}

GENERIC_SHORT_ANSWERS = {"有", "没有", "不知道", "不清楚", "忘了", "记不清", "记不太清"}
NEGATIVE_WORDS = {"无", "没有", "否", "未", "不疼", "没事", "正常", "阴性"}
UNKNOWN_PATTERN = re.compile(r"(不知道|不清楚|记不清|忘了|不确定|说不准)")
POSITIVE_MEDICATION_PATTERN = re.compile(r"(药|片|粒|胰岛素|注射|口服|服用|吃)")
NEGATIVE_MEDICATION_PATTERN = re.compile(r"(没吃药|未用药|没有用药|没用药)")
INSULIN_PATTERN = re.compile(r"(胰岛素)")
SURGERY_PATTERN = re.compile(r"(手术|支架|搭桥|介入|开刀)")
NEGATIVE_SURGERY_PATTERN = re.compile(r"(没做手术|未手术)")


def _clean_text(value):
    return str(value or "").strip()


def _append_reason(result, note):
    reasoning = _clean_text(result.get("reasoning"))
    if note and note not in reasoning:
        result["reasoning"] = f"{reasoning} {note}".strip()
    return result


def _extract_first_number(text):
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    return float(match.group())


def _normalize_yes_no(value):
    text = _clean_text(value)
    if not text:
        return ""

    if re.search(r"(没有|无|否认|不是|未患|未出现|没发生|阴性|正常)", text):
        return "否"
    if re.search(r"(有|是|患过|得过|出现过|疼过|阳性)", text):
        return "是"
    if re.search(r"(不知道|不清楚|记不清|忘了|不确定|说不准|应该)", text):
        return "未知"
    if text in {"是", "否", "未知"}:
        return text
    return text


def _normalize_height(value):
    text = _clean_text(value)
    if not text:
        return ""

    number = _extract_first_number(text)
    if number is None:
        return text

    # 小于 3 且提到“米”时，按米转厘米。
    if "米" in text and number < 3:
        number = round(number * 100)
    elif number < 3:
        number = round(number * 100)
    else:
        number = round(number)

    return f"{int(number)}cm"


def _normalize_weight(value):
    text = _clean_text(value)
    if not text:
        return ""

    number = _extract_first_number(text)
    if number is None:
        return text

    # 斤在真实对话里很常见，所以优先做斤 -> kg 的换算。
    if "斤" in text:
        number = round(number / 2, 1)
    elif number > 120:
        number = round(number / 2, 1)

    if float(number).is_integer():
        return f"{int(number)}kg"
    return f"{number}kg"


def _normalize_blood_pressure(value):
    text = _clean_text(value)
    if not text:
        return ""

    text = text.replace(" ", "")
    if "/" not in text:
        return text

    if text.endswith("mmHg"):
        return text
    return f"{text}mmHg"


def _normalize_numeric_with_unit(value, unit):
    text = _clean_text(value)
    if not text:
        return ""

    number = _extract_first_number(text)
    if number is None:
        return text

    if not unit:
        return str(int(number)) if float(number).is_integer() else str(number)
    if float(number).is_integer():
        return f"{int(number)}{unit}"
    return f"{number}{unit}"


def _looks_like_duration(value):
    text = _clean_text(value)
    if not text:
        return False
    return bool(re.search(r"(年|月|周|天|至今|术后|多年|余年|左右|间断|一直|一两次)", text))


def _looks_like_pain_score(value):
    text = _clean_text(value)
    if not text:
        return False
    number = _extract_first_number(text)
    return number is not None and 0 <= number <= 10


def _is_specific_text(value):
    text = _clean_text(value)
    if not text:
        return False
    if text in GENERIC_SHORT_ANSWERS:
        return False
    return len(text) >= 2


def _contains_unknown(text):
    return bool(UNKNOWN_PATTERN.search(_clean_text(text)))


def _slot_status_from_patterns(text, patterns, slot_keywords=None):
    clean = _clean_text(text)
    for pattern in patterns:
        if re.search(pattern, clean):
            return "answered"
    if slot_keywords:
        for keyword in slot_keywords:
            if re.search(rf"({keyword}).{{0,6}}(不知道|不清楚|记不清|忘了)", clean):
                return "unknown"
            if re.search(rf"(不知道|不清楚|记不清|忘了).{{0,6}}({keyword})", clean):
                return "unknown"
    elif _contains_unknown(clean):
        return "unknown"
    return "missing"


def _mentions_no_medication(text):
    return bool(NEGATIVE_MEDICATION_PATTERN.search(_clean_text(text)))


def _mentions_medication(text):
    clean = _clean_text(text)
    return bool(POSITIVE_MEDICATION_PATTERN.search(clean)) and not _mentions_no_medication(clean)


def _mentions_insulin(text):
    return bool(INSULIN_PATTERN.search(_clean_text(text)))


def _mentions_surgery(text):
    clean = _clean_text(text)
    return bool(SURGERY_PATTERN.search(clean)) and not bool(NEGATIVE_SURGERY_PATTERN.search(clean))


def _mark_not_applicable(slots, names):
    for name in names:
        slots[name] = "not_applicable"


def _has_status(slots, status):
    return any(value == status for value in slots.values())


def _evaluate_hypertension_medication_slots(text):
    slots = {
        "control_level": _slot_status_from_patterns(text, [r"\d+\s*/\s*\d+", r"血压"], ["血压"]),
    }
    if _mentions_medication(text):
        slots.update({
            "drug_name": _slot_status_from_patterns(text, [r"(硝苯地平|氨氯地平|缬沙坦|厄贝沙坦|替米沙坦|降压药)"], ["药", "药物"]),
            "spec": _slot_status_from_patterns(text, [r"\d+\s*(mg|毫克|g|克)"], ["规格", "mg", "毫克"]),
            "frequency": _slot_status_from_patterns(text, [r"(一天|每日|每天).{0,6}(次|回)"], ["次数", "频次", "一天", "每天"]),
            "dose_each_time": _slot_status_from_patterns(text, [r"(一次|每次).{0,8}(片|粒|颗)"], ["一次", "每次", "几片", "几粒"]),
        })
    else:
        _mark_not_applicable(slots, {"drug_name", "spec", "frequency", "dose_each_time"})
    return slots


def _evaluate_diabetes_medication_slots(text):
    slots = {
        "control_level": _slot_status_from_patterns(text, [r"(血糖|空腹血糖|\d+(?:\.\d+)?)"], ["血糖", "空腹血糖"]),
    }
    if _mentions_medication(text):
        slots.update({
            "drug_name": _slot_status_from_patterns(text, [r"(二甲双胍|阿卡波糖|达格列净|降糖药)"], ["药", "药物"]),
            "spec": _slot_status_from_patterns(text, [r"\d+\s*(mg|毫克|g|克)"], ["规格", "mg", "毫克"]),
            "frequency": _slot_status_from_patterns(text, [r"(一天|每日|每天).{0,6}(次|回)"], ["次数", "频次", "一天", "每天"]),
            "dose_each_time": _slot_status_from_patterns(text, [r"(一次|每次).{0,8}(片|粒|颗)"], ["一次", "每次", "几片", "几粒"]),
        })
    else:
        _mark_not_applicable(slots, {"drug_name", "spec", "frequency", "dose_each_time"})

    if _mentions_insulin(text):
        slots.update({
            "insulin_name": _slot_status_from_patterns(text, [r"(甘精胰岛素|门冬胰岛素|胰岛素)"], ["胰岛素"]),
            "injection_time": _slot_status_from_patterns(text, [r"(早上|中午|晚上|饭前|饭后|睡前)"], ["时间", "什么时候", "早上", "晚上"]),
            "injection_units": _slot_status_from_patterns(text, [r"\d+\s*(个单位|u|U)"], ["单位"]),
        })
    else:
        _mark_not_applicable(slots, {"insulin_name", "injection_time", "injection_units"})
    return slots


def _evaluate_coronary_treatment_slots(text):
    slots = {
        "treatment_type": _slot_status_from_patterns(text, [r"(手术|支架|搭桥|介入|药物|吃药|观察)"]),
        "stenosis": _slot_status_from_patterns(text, [r"(冠脉).{0,6}(狭窄|存在|没有)"]),
        "symptom_improved": _slot_status_from_patterns(text, [r"(好转|好多了|缓解|仍然|改善)"]),
        "recurred": _slot_status_from_patterns(text, [r"(再犯|再发|没再犯|没有再犯)"]),
    }
    if slots["treatment_type"] == "missing" and (_mentions_surgery(text) or _mentions_medication(text)):
        slots["treatment_type"] = "answered"
    if _mentions_surgery(text):
        slots.update({
            "surgery_time": _slot_status_from_patterns(text, [r"(19|20)\d{2}年|\d+年|\d+月"]),
            "surgery_type": _slot_status_from_patterns(text, [r"(支架|搭桥|介入|手术)"]),
        })
    else:
        _mark_not_applicable(slots, {"surgery_time", "surgery_type"})

    if _mentions_medication(text):
        slots.update({
            "drug_name": _slot_status_from_patterns(text, [r"(阿司匹林|氯吡格雷|阿托伐他汀|心脏药|降压药)"]),
            "spec": _slot_status_from_patterns(text, [r"\d+\s*(mg|毫克|g|克)"]),
            "frequency": _slot_status_from_patterns(text, [r"(一天|每日|每天).{0,6}(次|回)"]),
            "dose_each_time": _slot_status_from_patterns(text, [r"(一次|每次).{0,8}(片|粒|颗)"]),
        })
    else:
        _mark_not_applicable(slots, {"drug_name", "spec", "frequency", "dose_each_time"})
    return slots


def _evaluate_cerebrovascular_treatment_slots(text):
    slots = {
        "disease_name": _slot_status_from_patterns(text, [r"(脑梗|脑出血|脑血管病)"]),
        "treatment_type": _slot_status_from_patterns(text, [r"(手术|介入|药物|吃药|观察|保守治疗)"]),
        "symptom_improved": _slot_status_from_patterns(text, [r"(好转|好多了|缓解|仍然|改善)"]),
        "recurred": _slot_status_from_patterns(text, [r"(再犯|再发|没再犯|没有再犯)"]),
        "sequelae": _slot_status_from_patterns(text, [r"(后遗症|没有后遗症|遗留)"]),
    }
    if slots["treatment_type"] == "missing" and (_mentions_surgery(text) or _mentions_medication(text)):
        slots["treatment_type"] = "answered"
    if _mentions_surgery(text):
        slots.update({
            "surgery_time": _slot_status_from_patterns(text, [r"(19|20)\d{2}年|\d+年|\d+月"]),
            "surgery_type": _slot_status_from_patterns(text, [r"(开刀|介入|手术)"]),
        })
    else:
        _mark_not_applicable(slots, {"surgery_time", "surgery_type"})

    if _mentions_medication(text):
        slots.update({
            "drug_name": _slot_status_from_patterns(text, [r"(阿司匹林|氯吡格雷|他汀药|脑血管药|降压药)"]),
            "spec": _slot_status_from_patterns(text, [r"\d+\s*(mg|毫克|g|克)"]),
            "frequency": _slot_status_from_patterns(text, [r"(一天|每日|每天).{0,6}(次|回)"]),
            "dose_each_time": _slot_status_from_patterns(text, [r"(一次|每次).{0,8}(片|粒|颗)"]),
        })
    else:
        _mark_not_applicable(slots, {"drug_name", "spec", "frequency", "dose_each_time"})
    return slots


def _evaluate_other_history_treatment_slots(text):
    slots = {
        "disease_name": _slot_status_from_patterns(text, [r"(甲减|腰间盘突出|疾病|病史|病)"]),
        "treatment_type": _slot_status_from_patterns(text, [r"(手术|介入|药物|吃药|观察|保守治疗)"]),
        "symptom_improved": _slot_status_from_patterns(text, [r"(好转|好多了|缓解|仍然|改善|控制)"]),
        "recurred": _slot_status_from_patterns(text, [r"(再犯|再发|没再犯|没有再犯)"]),
    }
    if slots["treatment_type"] == "missing" and (_mentions_surgery(text) or _mentions_medication(text)):
        slots["treatment_type"] = "answered"
    if _mentions_surgery(text):
        slots.update({
            "surgery_time": _slot_status_from_patterns(text, [r"(19|20)\d{2}年|\d+年|\d+月"]),
            "surgery_type": _slot_status_from_patterns(text, [r"(手术|切除|介入)"]),
        })
    else:
        _mark_not_applicable(slots, {"surgery_time", "surgery_type"})

    if _mentions_medication(text):
        slots.update({
            "drug_name": _slot_status_from_patterns(text, [r"(优甲乐|止痛药|降压药|降糖药|药)"]),
            "spec": _slot_status_from_patterns(text, [r"\d+\s*(mg|毫克|g|克|ug)"]),
            "frequency": _slot_status_from_patterns(text, [r"(一天|每日|每天).{0,6}(次|回)"]),
            "dose_each_time": _slot_status_from_patterns(text, [r"(一次|每次).{0,8}(片|粒|颗)"]),
        })
    else:
        _mark_not_applicable(slots, {"drug_name", "spec", "frequency", "dose_each_time"})
    return slots


def _finalize_strict_complex_result(result, slots, note):
    adjusted = dict(result)
    if _has_status(slots, "missing"):
        adjusted["status"] = "ask_again"
        adjusted["completion"] = "partial" if _clean_text(adjusted.get("field_value")) else "empty"
    else:
        adjusted["status"] = "done"
        adjusted["completion"] = "complete"
    return _append_reason(adjusted, note)




def get_field_rule(field):
    return FIELD_RULES.get(field, {})


def build_field_rule_prompt(field):
    spec = get_field_rule(field)
    if not spec:
        return ""

    lines = ["字段级判定参考："]
    minimum_requirement = spec.get("minimum_requirement")
    accepted_examples = spec.get("accepted_examples")
    followup_focus = spec.get("followup_focus")

    if minimum_requirement:
        lines.append(f"- 最低可接受信息：{minimum_requirement}")
    if accepted_examples:
        lines.append(f"- 典型可接受示例：{'；'.join(accepted_examples)}")
    if followup_focus:
        lines.append(f"- 若需追问，优先追问：{followup_focus}")

    return "\n".join(lines)


def apply_field_completion_rules(field, result):
    adjusted = dict(result)
    status = adjusted.get("status", "ask_again")
    value = _clean_text(adjusted.get("field_value"))

    # later / manual_review 先保留给主流程，避免规则层过度覆盖。
    if status in {"later", "manual_review"}:
        return adjusted

    if field in YES_NO_FIELDS:
        normalized = _normalize_yes_no(value)
        if normalized in {"是", "否", "未知"}:
            adjusted["field_value"] = normalized
            adjusted["status"] = "done"
            adjusted["completion"] = "complete"
            return _append_reason(adjusted, "按是/否类字段规则收束。")
        return adjusted

    if field in HEIGHT_FIELDS:
        normalized = _normalize_height(value)
        if normalized and normalized.endswith("cm"):
            adjusted["field_value"] = normalized
            adjusted["status"] = "done"
            adjusted["completion"] = "complete"
            return _append_reason(adjusted, "按身高字段规则收束。")
        return adjusted

    if field in WEIGHT_FIELDS:
        normalized = _normalize_weight(value)
        if normalized and normalized.endswith("kg"):
            adjusted["field_value"] = normalized
            adjusted["status"] = "done"
            adjusted["completion"] = "complete"
            return _append_reason(adjusted, "按体重字段规则收束。")
        return adjusted

    if field in BLOOD_PRESSURE_FIELDS:
        normalized = _normalize_blood_pressure(value)
        if normalized and "/" in normalized:
            adjusted["field_value"] = normalized
            adjusted["status"] = "done"
            adjusted["completion"] = "complete"
            return _append_reason(adjusted, "按血压字段规则收束。")
        return adjusted

    if field in NUMERIC_FIELDS:
        normalized = _normalize_numeric_with_unit(value, NUMERIC_FIELDS[field])
        if _extract_first_number(normalized) is not None:
            adjusted["field_value"] = normalized
            adjusted["status"] = "done"
            adjusted["completion"] = "complete"
            return _append_reason(adjusted, "按数值型字段规则收束。")
        return adjusted

    if field in DURATION_FIELDS:
        if _looks_like_duration(value):
            adjusted["status"] = "done"
            adjusted["completion"] = "complete"
            return _append_reason(adjusted, "按时长字段规则收束。")
        return adjusted

    if field in PAIN_SCORE_FIELDS:
        if _looks_like_pain_score(value):
            adjusted["status"] = "done"
            adjusted["completion"] = "complete"
            return _append_reason(adjusted, "按疼痛评分字段规则收束。")
        return adjusted

    if field in TEXT_COMPLETE_FIELDS:
        normalized = _normalize_yes_no(value) if field == "其余病史及用药情况" else value
        if field == "其余病史及用药情况" and normalized in {"否", "无","未知","没有"}:
            adjusted["field_value"] = normalized
            adjusted["status"] = "done"
            adjusted["completion"] = "complete"
            return _append_reason(adjusted, "按其余病史字段规则收束。")

        if _is_specific_text(value):
            adjusted["status"] = "done"
            adjusted["completion"] = "complete"
            return _append_reason(adjusted, "按文本型字段规则收束。")
        return adjusted

    return adjusted
