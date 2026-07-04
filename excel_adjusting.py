import os

import openpyxl
from openpyxl.styles import Font


def format_excel(file_path, save_path=None):
    if save_path is None:
        save_path = file_path

    wb = openpyxl.load_workbook(file_path)

    for ws in wb.worksheets:
        ws.column_dimensions["A"].width = 45
        ws.column_dimensions["B"].width = 30
        ws.column_dimensions["C"].width = 50

        for row in ws.iter_rows():
            for cell in row:
                if cell.value:
                    has_chinese = any("\u4e00" <= char <= "\u9fff" for char in str(cell.value))
                    if has_chinese:
                        cell.font = Font(name="微软雅黑")
                    else:
                        cell.font = Font(name="Times New Roman")

    wb.save(save_path)
    return True


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, "medical_data.xlsx")
    if os.path.exists(file_path):
        format_excel(file_path, file_path)
