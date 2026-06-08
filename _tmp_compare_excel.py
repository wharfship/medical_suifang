import xlrd
book = xlrd.open_workbook('最后几个问题.xls')
sh = book.sheet_by_name('Sheet1')
headers = sh.row_values(0)
idx_field = headers.index('填写内容')
idx_desc = headers.index('字段含义')
idx_example = headers.index('示例')
expected_desc = '了解患者血清肌酐水平，单位umol/L，缺失时要建议患者去医院检查并上传单。'
expected_example = '请告诉我最近一次检查中的血清肌酐结果。'
for r in range(1, sh.nrows):
    if sh.cell_value(r, idx_field) == '血生化：血清肌酐':
        desc = sh.cell_value(r, idx_desc)
        example = sh.cell_value(r, idx_example)
        print('DESC_MATCH=', desc == expected_desc)
        print('EXAMPLE_MATCH=', example == expected_example)
        print('DESC_LEN=', len(desc))
        print('EXAMPLE_LEN=', len(example))
        print('DESC_UNICODE=', [hex(ord(ch)) for ch in desc[:20]])
        print('EXAMPLE_UNICODE=', [hex(ord(ch)) for ch in example[:20]])
