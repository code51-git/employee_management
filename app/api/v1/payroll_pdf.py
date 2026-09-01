import uuid
import os
from io import BytesIO
from datetime import date
from calendar import monthrange
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from reportlab.lib.enums import TA_JUSTIFY

from app.core.database import get_db
from app.core.permissions import everyone
from app.models.user import Payroll, User, UserProfile
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT

router = APIRouter(prefix="/payroll", tags=["Payroll Document Engine"])

GREEN = colors.HexColor('#4CAF50')
LIGHT_YELLOW = colors.HexColor('#FFF9C4')
BORDER = colors.black

# ── Amount-in-words (Indian numbering: lakh/crore) 
_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
         "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
         "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two_digit_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    return (_TENS[n // 10] + (f" {_ONES[n % 10]}" if n % 10 else "")).strip()


def _three_digit_words(n: int) -> str:
    if n >= 100:
        rest = n % 100
        return f"{_ONES[n // 100]} Hundred" + (f" {_two_digit_words(rest)}" if rest else "")
    return _two_digit_words(n)


def number_to_words_inr(amount: float) -> str:
    n = int(round(amount))
    if n == 0:
        return "Zero"
    parts = []
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1_000)
    hundred = n

    if crore:
        parts.append(f"{_three_digit_words(crore)} Crore")
    if lakh:
        parts.append(f"{_three_digit_words(lakh)} Lakh")
    if thousand:
        parts.append(f"{_three_digit_words(thousand)} Thousand")
    if hundred:
        parts.append(_three_digit_words(hundred))

    return " ".join(parts) if parts else "Zero"


def fmt_amount(v) -> str:
    v = float(v or 0)
    return f"{v:,.0f}" if v else "-"


@router.get("/{payroll_id}/pdf")
async def generate_payroll_pdf(
    payroll_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    result = await db.execute(
        select(Payroll)
        .options(joinedload(Payroll.user).joinedload(User.profile))
        .where(Payroll.id == payroll_id)
    )
    payroll = result.scalars().first()

    if not payroll:
        raise HTTPException(status_code=404, detail="Payroll record not found.")

    caller_id = current_user.get("sub")
    caller_role = current_user.get("role")
    if caller_role not in ["super_admin", "hr_admin"] and str(payroll.user_id) != str(caller_id):
        raise HTTPException(status_code=403, detail="Permission Denied.")

    employee = payroll.user
    profile = employee.profile if employee else None

    full_name = "Employee Account"
    employee_id = "N/A"
    designation = "N/A"
    pan_number = "N/A"
    doj_display = "N/A"

    if profile:
        full_name = f"{profile.first_name} {profile.last_name}".strip() or "Employee Account"
        employee_id = profile.employee_id or "N/A"
        designation = profile.designation or "N/A"
        pan_number = getattr(profile, "pan_number", None) or "N/A"  # ASSUMPTION: field name
        if profile.date_of_joining:
            doj_display = profile.date_of_joining.strftime("%d-%m-%Y") \
                if hasattr(profile.date_of_joining, "strftime") else str(profile.date_of_joining)

    if isinstance(payroll.salary_month, date):
        month_display = payroll.salary_month.strftime("%b-%y")  # e.g. "Jan-26"
        working_days_in_month = monthrange(payroll.salary_month.year, payroll.salary_month.month)[1]
    else:
        month_display = str(payroll.salary_month)
        working_days_in_month = 30

    # ASSUMPTION: no explicit working_days/paid_days columns on Payroll yet —
    # falling back to calendar days minus LOP. Swap in real fields if you add them.
    working_days = getattr(payroll, "working_days", working_days_in_month)
    lop_days = float(payroll.lop_days or 0)
    paid_days = getattr(payroll, "paid_days", working_days - lop_days)

    # Earnings figures
    basic = float(payroll.basic_salary or 0)
    hra = float(payroll.hra or 0)
    conveyance = float(payroll.travel_allowance or 0)          # ASSUMPTION
    ot = float(payroll.overtime_pay or 0)                      # ASSUMPTION
    incentive = float(getattr(payroll, "incentive", 0) or 0)   # ASSUMPTION
    bonus = float(getattr(payroll, "bonus", 0) or 0)           # ASSUMPTION
    other_allowance = float(payroll.allowances or 0) + float(payroll.health_allowance or 0)  # ASSUMPTION
    gross = float(payroll.gross_salary or (basic + hra + conveyance + ot + incentive + bonus + other_allowance))

    # Deduction figures
    advance = float(payroll.advance_deduction or 0)
    other_deduction = float(payroll.deductions or 0) + float(payroll.lop_deduction or 0)  # ASSUMPTION
    total_deductions = advance + other_deduction

    net_salary = float(payroll.net_salary or (gross - total_deductions))

    # ── PDF setup ─────────────────────────────────────────────────────────
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=50, leftMargin=50, topMargin=40, bottomMargin=40
    )
    styles = getSampleStyleSheet()
    normal = styles['Normal']
    small_grey = ParagraphStyle('SmallGrey', parent=normal, fontSize=8, textColor=colors.grey, alignment=TA_RIGHT)
    company_name_style = ParagraphStyle('CompanyName', parent=styles['Heading1'], fontSize=20, leading=22)
    tagline_style = ParagraphStyle('Tagline', parent=normal, fontSize=9, textColor=colors.grey)
    title_style = ParagraphStyle('Title', parent=normal, fontSize=13, alignment=TA_CENTER,
                                  textColor=colors.white, fontName='Helvetica-Bold')
    label_style = ParagraphStyle('Label', parent=normal, fontSize=9, fontName='Helvetica-Bold')
    value_style = ParagraphStyle('Value', parent=normal, fontSize=9)
    section_hdr_style = ParagraphStyle('SectionHdr', parent=normal, fontSize=10, fontName='Helvetica-Bold',
                                        textColor=colors.white)
    right_amount = ParagraphStyle('RightAmount', parent=normal, fontSize=9, alignment=TA_RIGHT)
    net_label_style = ParagraphStyle('NetLabel', parent=normal, fontSize=11, fontName='Helvetica-Bold',
                                      textColor=colors.white, alignment=TA_CENTER)
    footer_style = ParagraphStyle('Footer', parent=normal, fontSize=8, textColor=colors.grey,
                                   alignment=TA_CENTER, fontName='Helvetica-Oblique')

    elements = []

# ── Header: logo + company info ──────────────────────────────────────
    logo_path = os.path.join(os.getcwd(), "static", "logo", "c51-logo.png")

    LOGO_WIDTH = 95
    LOGO_HEIGHT = 36

    if os.path.exists(logo_path):
        logo_img = Image(logo_path, width=LOGO_WIDTH, height=LOGO_HEIGHT)
    else:
        logo_img = Paragraph("<b>code51</b>", company_name_style)

    tagline_style_justified = ParagraphStyle(
        'TaglineJustified',
        parent=normal,
        fontSize=7,
        textColor=colors.black,
        leading=8,
        alignment=TA_JUSTIFY,   # ← stretches the single line to fill colWidths exactly
    )

    logo_block = Table(
        [[logo_img], [Paragraph("Fifty one code solutions Pvt.ltd", tagline_style_justified)]],
        colWidths=[LOGO_WIDTH]   # tagline forced to the exact same width as the logo
    )
    logo_block.setStyle(TableStyle([
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))

    header_right = Paragraph(
        "code51.in<br/>info@code51.in<br/><br/>"
        "1st Floor, Presidency Vintage<br/>Kankanady, Mangalore - 575002",
        small_grey
    )
    header_table = Table([[logo_block, header_right]], colWidths=[280, 260])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 10))

    # ── Title banner ──────────────────────────────────────────────────────
    title_banner = Table([[Paragraph("SALARY PAYSLIP", title_style)]], colWidths=[520])
    title_banner.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), GREEN),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('BOX', (0, 0), (-1, -1), 1, BORDER),
    ]))
    elements.append(title_banner)

    # ── Info grid ─────────────────────────────────────────────────────────
    def info_row(l1, v1, l2, v2):
        return [Paragraph(l1, label_style), Paragraph(str(v1), value_style),
                Paragraph(l2, label_style), Paragraph(str(v2), value_style)]

    info_data = [
        info_row("Employee ID", employee_id, "Month", month_display),
        info_row("Employee Name", full_name, "Designation", designation),
        info_row("PAN No.", pan_number, "DOJ", doj_display),
        info_row("Working Days", f"{working_days:g}" if isinstance(working_days, float) else working_days,
                  "Paid Days", f"{paid_days:g}" if isinstance(paid_days, float) else paid_days),
    ]
    info_table = Table(info_data, colWidths=[110, 150, 110, 150])
    info_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 1, BORDER),
        ('INNERGRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#dddddd')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(info_table)

    # ── EARNINGS banner ───────────────────────────────────────────────────
    earnings_banner = Table([[Paragraph("EARNINGS", section_hdr_style)]], colWidths=[520])
    earnings_banner.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), GREEN),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LINEABOVE', (0, 0), (-1, -1), 1, BORDER),
        ('LINEBELOW', (0, 0), (-1, -1), 0, BORDER),
        ('LINEBEFORE', (0, 0), (-1, -1), 1, BORDER),
        ('LINEAFTER', (0, 0), (-1, -1), 1, BORDER),
    ]))
    elements.append(earnings_banner)

    # ── Earnings / Deductions grid ────────────────────────────────────────
    def row(label, amount, label2="", amount2=""):
        return [
            Paragraph(label, value_style), Paragraph(fmt_amount(amount) if amount != "" else "", right_amount),
            Paragraph(label2, value_style), Paragraph(fmt_amount(amount2) if amount2 != "" else "", right_amount),
        ]

    grid_data = [
        row("Basic Salary", basic, "Advance", advance),
        row("HRA", hra, "Other Deduction", other_deduction),
        row("Conveyance", conveyance),
        row("OT", ot),
        row("Incentive", incentive),
        row("Bonus", bonus),
        row("Other Allowance", other_allowance),
        [Paragraph("<b>Gross Earnings</b>", label_style), Paragraph(f"<b>{fmt_amount(gross)}</b>", right_amount),
         Paragraph("<b>Total Deductions</b>", label_style), Paragraph(f"<b>{fmt_amount(total_deductions)}</b>", right_amount)],
    ]
    grid_table = Table(grid_data, colWidths=[160, 100, 160, 100])
    grid_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 1, BORDER),
        ('INNERGRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#dddddd')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f2f2f2')),
    ]))
    elements.append(grid_table)

    # ── Net Salary Payable banner ────────────────────────────────────────
    net_table = Table(
        [[Paragraph("Net Salary Payable", net_label_style), Paragraph(f"<b>{fmt_amount(net_salary)}</b>", right_amount)]],
        colWidths=[260, 260]
    )
    net_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), GREEN),
        ('BOX', (0, 0), (-1, -1), 1, BORDER),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (0, -1), 14),
        ('RIGHTPADDING', (1, 0), (1, -1), 14),
        ('TEXTCOLOR', (1, 0), (1, -1), colors.white),
        ('FONTSIZE', (1, 0), (1, -1), 11),
    ]))
    elements.append(net_table)
    elements.append(Spacer(1, 6))

    # ── In Words ──────────────────────────────────────────────────────────
    words_table = Table(
        [[Paragraph(f"<b>In Words:</b>  Rupees {number_to_words_inr(net_salary)} Only", value_style)]],
        colWidths=[520]
    )
    words_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), LIGHT_YELLOW),
        ('BOX', (0, 0), (-1, -1), 1, BORDER),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
    ]))
    elements.append(words_table)
    elements.append(Spacer(1, 24))

    # ── Footer ────────────────────────────────────────────────────────────
    elements.append(Paragraph("This is a computer generated payslip and does not require signature.", footer_style))

    doc.build(elements)
    buffer.seek(0)

    safe_name = full_name.replace(" ", "_").lower()
    filename = f"payslip_{safe_name}_{month_display.replace(' ', '_')}.pdf"

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
