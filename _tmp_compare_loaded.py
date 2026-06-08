from statistic_preprocessing import load_excel_template
meta = load_excel_template('最后几个问题.xls')
field = '血生化：血清肌酐'
expected_example = '请告诉我最近一次检查中的血清肌酐结果。'
print('LOADED_EXAMPLE_MATCH=', meta[field]['示例'] == expected_example)
print('LOADED_DESC_RAW_LEN=', len(meta[field]['描述']))
print('LOADED_EXAMPLE_RAW_LEN=', len(meta[field]['示例']))
