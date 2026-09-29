import re
from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "LLM多智能体社会经济仿真研究报告_2026.md"
OUTPUT = SOURCE.with_suffix(".docx")
FONT_PATH = "C:/Windows/Fonts/msyh.ttc"


def draw_diagram():
    canvas = Image.new("RGB", (1700, 670), "white")
    drawing = ImageDraw.Draw(canvas)
    title_font = ImageFont.truetype(FONT_PATH, 32)
    body_font = ImageFont.truetype(FONT_PATH, 25)
    small_font = ImageFont.truetype(FONT_PATH, 23)
    dark = "#243746"
    border = "#7D93A5"
    drawing.rounded_rectangle((65, 25, 1635, 130), radius=12, fill="#EDF2F6", outline=border, width=2)
    drawing.text((90, 43), "实验控制器", font=title_font, fill=dark)
    drawing.text((90, 88), "冻结假设与配置  ·  初始化与干预  ·  模型和随机性管理  ·  成本控制", font=body_font, fill=dark)
    boxes = [
        (65, "LLM 智能体", ["身份与局部观察", "事件与关系记忆", "规划  反思  工具"]),
        (465, "社会通信层", ["询价与协商", "承诺与声誉", "信息来源与网络"]),
        (865, "执行验证器", ["动作与权限校验", "合同与资源约束", "拒绝与错误反馈"]),
        (1265, "经济环境", ["订单与交易", "库存与结算", "政策与外生冲击"]),
    ]
    for left, title, lines in boxes:
        drawing.rounded_rectangle((left, 210, left + 370, 440), radius=12, fill="#FAFBFC", outline=border, width=2)
        drawing.text((left + 22, 234), title, font=title_font, fill=dark)
        for line_number, line in enumerate(lines):
            drawing.text((left + 22, 302 + line_number * 38), line, font=body_font, fill=dark)
    for left in [435, 835, 1235]:
        drawing.line((left + 4, 324, left + 24, 324), fill=dark, width=3)
        drawing.polygon([(left + 25, 324), (left + 16, 318), (left + 16, 330)], fill=dark)
    drawing.line((1445, 443, 1445, 495, 245, 495, 245, 446), fill=dark, width=3)
    drawing.polygon([(245, 444), (238, 455), (252, 455)], fill=dark)
    drawing.text((588, 457), "局部观察与行动结果反馈", font=small_font, fill=dark)
    drawing.rounded_rectangle((65, 550, 1635, 647), radius=12, fill="#EDF2F6", outline=border, width=2)
    drawing.text((90, 566), "评价与审计", font=title_font, fill=dark)
    drawing.text((90, 609), "结构化日志  ·  轨迹回放  ·  多层指标  ·  机制消融  ·  外部验证与适用边界", font=small_font, fill=dark)
    canvas.save(ROOT / "research" / "architecture.png")


def set_font(style, name, size, bold=False):
    style.font.name = name
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.italic = False
    style.font.underline = False
    style.font.color.rgb = RGBColor(0, 0, 0)
    properties = style.element.get_or_add_rPr()
    fonts = properties.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        properties.insert(0, fonts)
    for attribute in ["ascii", "hAnsi", "eastAsia", "cs"]:
        fonts.set(qn("w:" + attribute), name)
    for attribute in ["ascii", "hAnsi"]:
        fonts.set(qn("w:" + attribute), "Times New Roman" if name == "宋体" else "Arial")
    color = properties.find(qn("w:color"))
    if color is not None:
        for attribute in ["themeColor", "themeTint", "themeShade"]:
            color.attrib.pop(qn("w:" + attribute), None)


def add_hyperlink(paragraph, label, url):
    relationship = paragraph.part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink", is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), relationship)
    run = OxmlElement("w:r")
    properties = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "245477")
    properties.append(color)
    run.append(properties)
    text_element = OxmlElement("w:t")
    text_element.text = label
    run.append(text_element)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def add_text(paragraph, text):
    cursor = 0
    for match in re.finditer(r"\[([^\]]+)\]\((https?://[^)]+)\)", text):
        paragraph.add_run(text[cursor:match.start()])
        add_hyperlink(paragraph, match.group(1), match.group(2))
        cursor = match.end()
    paragraph.add_run(text[cursor:])


def make_table(document, rows):
    table = document.add_table(rows=1, cols=len(rows[0]))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    widths = [3.3, 5.0, 4.0, 4.3] if len(rows[0]) == 4 else [4.1, 6.3, 6.2]
    for column, width in zip(table.columns, widths):
        column.width = Cm(width)
    properties = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for side in ["top", "left", "bottom", "right", "insideH", "insideV"]:
        border = OxmlElement("w:" + side)
        border.set(qn("w:val"), "single")
        border.set(qn("w:sz"), "4")
        border.set(qn("w:color"), "D9D9D9")
        borders.append(border)
    properties.append(borders)
    for row_number, values in enumerate(rows):
        row = table.rows[0] if row_number == 0 else table.add_row()
        row_properties = row._tr.get_or_add_trPr()
        row_properties.append(OxmlElement("w:cantSplit"))
        if row_number == 0:
            row_properties.append(OxmlElement("w:tblHeader"))
        for column_number, value in enumerate(values):
            cell = row.cells[column_number]
            cell.width = Cm(widths[column_number])
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            cell_properties = cell._tc.get_or_add_tcPr()
            margins = OxmlElement("w:tcMar")
            for side, size in [("top", "90"), ("bottom", "90"), ("left", "100"), ("right", "100")]:
                margin = OxmlElement("w:" + side)
                margin.set(qn("w:w"), size)
                margin.set(qn("w:type"), "dxa")
                margins.append(margin)
            cell_properties.append(margins)
            shading = OxmlElement("w:shd")
            shading.set(qn("w:fill"), "DCE8F1" if row_number == 0 else ("F6F8FA" if row_number % 2 == 0 else "FFFFFF"))
            cell_properties.append(shading)
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(0)
            paragraph.paragraph_format.line_spacing = 1.12
            paragraph.paragraph_format.keep_with_next = row_number == 0 or (len(rows) <= 5 and row_number < len(rows) - 1)
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER if row_number == 0 else WD_ALIGN_PARAGRAPH.LEFT
            add_text(paragraph, value)
            for run in paragraph.runs:
                run.font.size = Pt(9.5)
                run.bold = row_number == 0
    spacer = document.add_paragraph()
    spacer.paragraph_format.space_after = Pt(2)
    spacer.paragraph_format.space_before = Pt(0)
    spacer.paragraph_format.line_spacing = 0.35
    spacer.add_run().font.size = Pt(2)


def build():
    draw_diagram()
    document = Document()
    section = document.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.05)
    section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(2.2)
    section.right_margin = Cm(2.2)
    section.footer_distance = Cm(0.85)
    for name, font, size, bold in [
        ("Normal", "宋体", 11, False),
        ("Title", "黑体", 23, False),
        ("Subtitle", "黑体", 13, False),
        ("Heading 1", "黑体", 16, False),
        ("Heading 2", "黑体", 12.5, False),
        ("Caption", "宋体", 9, False),
    ]:
        set_font(document.styles[name], font, size, bold)
    normal = document.styles["Normal"].paragraph_format
    normal.line_spacing = 1.25
    normal.space_after = Pt(6)
    normal.widow_control = True
    for name in ["Heading 1", "Heading 2"]:
        paragraph_format = document.styles[name].paragraph_format
        paragraph_format.keep_with_next = True
        paragraph_format.space_before = Pt(14 if name == "Heading 1" else 10)
        paragraph_format.space_after = Pt(7)
    document.styles["Title"].paragraph_format.space_after = Pt(13)
    document.styles["Title"].paragraph_format.line_spacing = 1.2
    document.styles["Subtitle"].paragraph_format.space_after = Pt(12)
    for border in document.styles.element.xpath(".//w:pBdr"):
        border.getparent().remove(border)
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer_run = footer.add_run()
    footer_run.font.size = Pt(9)
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    document.core_properties.title = "基于大语言模型的可信多智能体社会经济系统仿真"
    document.core_properties.subject = "2026 年研究进展与项目设计"
    document.core_properties.author = ""
    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    row_number = 0
    references = False
    while row_number < len(lines):
        line = lines[row_number].strip()
        if not line:
            row_number += 1
            continue
        if line.startswith("| "):
            table_rows = []
            while row_number < len(lines) and lines[row_number].strip().startswith("|"):
                cells = [value.strip() for value in lines[row_number].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", value) for value in cells):
                    table_rows.append(cells)
                row_number += 1
            make_table(document, table_rows)
            continue
        if line.startswith("# "):
            document.add_paragraph("基于大语言模型的可信多智能体\n社会经济系统仿真", "Title")
        elif line.startswith("## "):
            references = "参考文献" in line
            heading = document.add_paragraph(line[3:], "Heading 1")
        elif line.startswith("### "):
            document.add_paragraph(line[4:], "Heading 2")
        elif line.startswith("!["):
            image_path = re.search(r"\]\(([^)]+)\)", line).group(1)
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.keep_with_next = True
            picture = paragraph.add_run().add_picture(str(ROOT / image_path), width=Cm(16.4))
            picture._inline.docPr.set("descr", "建议系统架构，展示实验控制、LLM 智能体、社会通信、执行验证、经济环境及评价审计的关系")
        elif line.startswith("图 1"):
            document.add_paragraph(line, "Caption")
        elif line == "2026 年研究进展与项目设计":
            document.add_paragraph(line, "Subtitle")
        else:
            paragraph = document.add_paragraph()
            add_text(paragraph, line)
            if references:
                paragraph.paragraph_format.keep_together = True
                paragraph.paragraph_format.line_spacing = 1.12
                paragraph.paragraph_format.space_after = Pt(7)
                for run in paragraph.runs:
                    run.font.size = Pt(9.5)
            if line.startswith("调研截止日期"):
                for run in paragraph.runs:
                    run.font.size = Pt(10)
            if line.startswith("This project investigates"):
                paragraph.paragraph_format.keep_together = True
        row_number += 1
    document.save(OUTPUT)
    print(str(OUTPUT))


if __name__ == "__main__":
    build()
