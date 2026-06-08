from statistic_preprocessing import load_excel_template
from pathlib import Path
meta = load_excel_template(str(Path("最后几个问题.xls")))
for k, v in meta.items():
    print(f"{k}\t{v.get('追问上限')}")
