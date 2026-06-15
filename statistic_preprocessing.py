import pandas as pd
import re

# 各字段的默认追问上限
# 简单是/否类问题设为1，复杂多子问题设为4，其余默认2
DEFAULT_MAX_ATTEMPTS = {
    # ---- 简单是/否类，1次即可 ----
    "当前有无高血压": 1,
    "当前有无糖尿病": 1,
    "是否曾患冠心病": 1,
    "是否曾患脑血管病": 1,
    "近一年是否存在手术切口疼痛": 2,
    "（若有高血压）是否为过去一年新发": 1,
    "（若有糖尿病）是否为过去一年新发": 1,
    "（若曾患冠心病）是否为过去一年新发": 1,
    "（若曾患脑血管病）是否为过去一年新发": 1,
    "（若无高血压）过去一年有无出现血压升高": 1,
    "（若无糖尿病）过去一年有无出现空腹血糖升高": 1,
    # ---- 中等，2次 ----
    "当前身高": 2,
    "当前体重": 2,
    "当前血压": 2,
    "当前空腹血糖": 2,
    "（若有高血压）发现高血压至今时间": 2,
    "（若有高血压）最高达": 2,
    "（若有糖尿病）发现糖尿病至今时间": 2,
    "（若有糖尿病）最高达": 2,
    "（若有糖尿病）糖化血红蛋白": 2,
    "（若曾患冠心病）罹患冠心病至今时间": 2,
    "（若曾患脑血管病）罹患脑血管病至今时间": 2,
    "其余病史及用药情况": 2,
    "（若存在手术切口疼痛）手术切口疼痛持续时间": 2,
    "（若存在手术切口疼痛）疼痛程度评分": 2,
    "随访时受者状态": 2,
    "血生化：血清肌酐": 3,
    "尿常规：尿蛋白、尿潜血": 3,
    "肾脏彩超": 3,
    "请问您最近有去医院进行检查吗？": 2,
    # ---- 复杂多子问题，4次 ----
    "（若有高血压）药物控制方案": 4,
    "（若有糖尿病）药物控制方案": 4,
    "（若曾患冠心病）治疗方式": 4,
    "（若曾患脑血管病）具体疾病、治疗方式及有无后遗症": 4,
    "（若有其余病史）请描述具体疾病、治疗方式、用药种类、用法、治疗效果": 4,
}

HOSPITAL_CHECK_GATE_FIELD = "请问您最近有去医院进行检查吗？"
HOSPITAL_CHECK_CHILD_FIELDS = (
    "血生化：血清肌酐",
    "尿常规：尿蛋白、尿潜血",
    "肾脏彩超",
)
FIELD_EXAMPLE_OVERRIDES = {
    "随访时受者状态": "请告诉我最近一次检查中您的受者状态。A:移植肾功能正常（在检查医院肌酐指标的正常范围内）  B:移植肾功能不全（高于检查医院肌酐指标的正常范围） C:恢复透析（受者恢复透析状态） D：受者死亡",
}


def extract_dependencies(field):
    """解析字段依赖关系，支持多种条件前缀"""
    dependencies = {}
    # 定义支持的条件前缀列表
    condition_prefixes = ["若有高血压","若无高血压", "若有糖尿病","若无糖尿病", "若曾患冠心病", "若曾患脑血管病","若有其余病史","若存在手术切口疼痛"]
    # 检查字段名是否包含任何条件前缀
    # 这段代码的作用是给有依赖条件的子字段设定父字段，只有在父字段满足条件为“是”的情况下才会运行这个子字段。
    #比如“（若有高血压）是否为过去一年新发”的父字段为“当前有无高血压”，当“当前有无高血压”的值为“是”的时候才能运行（若有高血压）是否为过去一年新发
    for pattern_str in condition_prefixes:
        # 构建带括号的条件模式，当满足conditon满足条件时：，才会触发提问该问题,另外'opposite_condition'指的是当值不为'opposite_condition'时会触发提问
        if pattern_str in field:
            if pattern_str == "若有高血压":
                dependencies = {'parent': '当前有无高血压','condition':['是']}
            if pattern_str == "若无高血压":
                dependencies = {'parent': '当前有无高血压','condition': ['否','未知']}
            if pattern_str == "若有糖尿病":
                dependencies = {'parent': '当前有无糖尿病', 'condition': '是'}
            if pattern_str == "若无糖尿病":
                dependencies = {'parent': '当前有无糖尿病','condition': ['否','未知']}
            if pattern_str == "若曾患冠心病":
                dependencies = {'parent': '是否曾患冠心病', 'condition': ['是']}
            if pattern_str == "若曾患脑血管病":
                dependencies = {'parent': '是否曾患脑血管病', 'condition':['是']}
            if pattern_str == "若有其余病史":
                dependencies = {'parent': '其余病史及用药情况', 'opposite_condition': ['否','未知']}
            if pattern_str == "若存在手术切口疼痛":
                dependencies = {'parent': '近一年是否存在手术切口疼痛', 'condition': ['是']}
                break  # 找到匹配后退出循环
    return dependencies


def load_excel_template(file_path):
    """读取Excel文件并提取关键信息"""
    # 读取Excel文件
    df = pd.read_excel(file_path, sheet_name="Sheet1")

    # 创建空字典存储字段信息
    field_info = {}

    # 遍历每一行
    for index, row in df.iterrows():
        # 获取字段名称
        field = row['填写内容']

        # 跳过空行
        if pd.isna(field):
            continue
        # 获取字段描述和示例
        description = row['字段含义']
        example = row['示例'] if '示例' in row and not pd.isna(row['示例']) else ""

        # 解析依赖关系
        dependencies = extract_dependencies(field)
        # 存储字段信息，这是一个嵌套结构，field_name是一个键，里面的值就是 {}内部的值，但是{}里面又分出来三个键
        #分别是'描述'，'示例'，'依赖'，冒号也就是“：”后面的就是他们的值。
        #field_info是一级字典，{}里面的内容是二级字典，访问字典的某个字段的方式为：字典[键]
        #给某个键赋值的方法就是下面这个方法，如果只是单一结构，那只需要field_info['症状'] = '头痛'，嵌套的话就得用大括号{}了
        # 读取 Excel 中的「追问上限」列（若有），否则从 DEFAULT_MAX_ATTEMPTS 查找，最终兜底为 2
        if '追问上限' in row and not pd.isna(row['追问上限']):
            max_attempts = int(row['追问上限'])
        else:
            max_attempts = DEFAULT_MAX_ATTEMPTS.get(field, 4)

        field_info[field] = {
            '描述': description,
            '示例': FIELD_EXAMPLE_OVERRIDES.get(field, example),
            '依赖': dependencies,
            '追问上限': max_attempts
        }

    if all(field in field_info for field in HOSPITAL_CHECK_CHILD_FIELDS):
        ordered_items = list(field_info.items())
        first_child_index = next(
            index for index, (name, _) in enumerate(ordered_items) if name in HOSPITAL_CHECK_CHILD_FIELDS
        )
        if HOSPITAL_CHECK_GATE_FIELD not in field_info:
            gate_field = {
                '描述': '判断患者最近是否去医院做过相关检查；只有明确做过检查时，才继续询问后续化验和影像问题。',
                '示例': '请问您最近有去医院进行检查吗？',
                '依赖': {},
                '追问上限': DEFAULT_MAX_ATTEMPTS.get(HOSPITAL_CHECK_GATE_FIELD, 2),
            }
            ordered_items.insert(first_child_index, (HOSPITAL_CHECK_GATE_FIELD, gate_field))

        rebuilt = []
        for name, info in ordered_items:
            current = dict(info)
            if name in HOSPITAL_CHECK_CHILD_FIELDS:
                current['依赖'] = {'parent': HOSPITAL_CHECK_GATE_FIELD, 'condition': ['是']}
            if name in FIELD_EXAMPLE_OVERRIDES:
                current['示例'] = FIELD_EXAMPLE_OVERRIDES[name]
            rebuilt.append((name, current))
        field_info = dict(rebuilt)

    return field_info
