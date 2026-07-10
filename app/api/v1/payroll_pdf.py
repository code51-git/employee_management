import uuid
import os
from io import BytesIO
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload

from app.core.database import get_db
from app.core.permissions import everyone
from app.models.user import Payroll, User, UserProfile
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

router = APIRouter(prefix="/payroll", tags=["Payroll Document Engine"])


@router.get("/{payroll_id}/pdf")
async def generate_payroll_pdf(
    payroll_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):

    #  Fetch payroll + user + profile 
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

    #  Resolve names 
    full_name = "Employee Account"
    employee_id = "N/A"
    department = "N/A"
    designation = "N/A"

    if profile:
        full_name = f"{profile.first_name} {profile.last_name}".strip() or "Employee Account"
        employee_id = profile.employee_id or "N/A"
        department = profile.department or "N/A"
        designation = profile.designation or "N/A"

    #  Format salary month 
    if isinstance(payroll.salary_month, date):
        salary_month_display = payroll.salary_month.strftime("%B %Y")  # e.g. "June 2026"
    else:
        salary_month_display = str(payroll.salary_month)

    #  PDF Setup 
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'DocTitle', parent=styles['Heading1'],
        fontSize=20, leading=24,
        textColor=colors.HexColor('#1976d2'), alignment=0
    )
    section_heading = ParagraphStyle(
        'SectionHeading', parent=styles['Heading3'],
        fontSize=11, leading=16,
        textColor=colors.white,
        spaceBefore=15, spaceAfter=0,
        leftIndent=6
    )
    normal = styles['Normal']
    right_align = ParagraphStyle('RightAlign', parent=styles['Normal'], alignment=2)
    bold_right = ParagraphStyle('BoldRight', parent=styles['Normal'], alignment=2)

    elements = []

    #  Logo Header 
    logo_path = "app/static/logo.png"
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=100, height=40)
        header_data = [[Paragraph("OFFICIAL PAYSLIP", title_style), logo]]
    else:
        header_data = [[Paragraph("OFFICIAL PAYSLIP", title_style), Paragraph("<b>[Logo]</b>", normal)]]

    header_table = Table(header_data, colWidths=[380, 140])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    elements.append(header_table)

    # Divider
    divider = Table([[""]], colWidths=[520])
    divider.setStyle(TableStyle([('LINEBELOW', (0, 0), (-1, -1), 1.5, colors.HexColor('#1976d2'))]))
    elements.append(divider)
    elements.append(Spacer(1, 12))

    #  Salary Month Banner 
    month_banner = Table(
        [[Paragraph(f"<b>Pay Period: {salary_month_display}</b>", ParagraphStyle('Banner', parent=normal, textColor=colors.white, fontSize=11))]],
        colWidths=[520]
    )
    month_banner.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#1976d2')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
    ]))
    elements.append(month_banner)
    elements.append(Spacer(1, 12))

    #  Employee Info 
    def section_header(title):
        t = Table(
            [[Paragraph(f"<b>{title}</b>", section_heading)]],
            colWidths=[520]
        )
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#424242')),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        return t

    elements.append(section_header("Employee Information"))
    elements.append(Spacer(1, 6))

    emp_data = [
        [Paragraph(f"<b>Name:</b> {full_name}", normal),
         Paragraph(f"<b>Employee ID:</b> {employee_id}", normal)],
        [Paragraph(f"<b>Email:</b> {employee.email if employee else 'N/A'}", normal),
         Paragraph(f"<b>Department:</b> {department}", normal)],
        [Paragraph(f"<b>Designation:</b> {designation}", normal),
         Paragraph(f"<b>Generated:</b> {payroll.generated_at.strftime('%d %b %Y')}", normal)],
        [Paragraph(f"<b>Pay Slip Ref:</b> {str(payroll.id)[:8].upper()}", normal),
         Paragraph(f"<b>Status:</b> {payroll.status.value.upper()}", normal)],
    ]
    emp_table = Table(emp_data, colWidths=[260, 260])
    emp_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#eeeeee')),
    ]))
    elements.append(emp_table)
    elements.append(Spacer(1, 10))

    #  Attendance & Leave Summary 
    elements.append(section_header("Attendance & Leave Summary"))
    elements.append(Spacer(1, 6))

    leave_data = [
        [
            Paragraph("<b>Total Leave Days</b>", normal),
            Paragraph(str(payroll.total_leave_days), right_align),
            Paragraph("<b>Sick Leave Days</b>", normal),
            Paragraph(str(payroll.sick_leave_days), right_align),
        ],
        [
            Paragraph("<b>Casual Leave Days</b>", normal),
            Paragraph(str(payroll.casual_leave_days), right_align),
            Paragraph("<b>Loss of Pay (LOP) Days</b>", normal),
            Paragraph(str(payroll.lop_days), right_align),
        ],
    ]
    leave_table = Table(leave_data, colWidths=[160, 100, 160, 100])
    leave_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dddddd')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fafafa')),
    ]))
    elements.append(leave_table)
    elements.append(Spacer(1, 10))

    #  Earnings & Deductions 
    elements.append(section_header("Earnings & Deductions Breakdown"))
    elements.append(Spacer(1, 6))

    # Earnings
    earnings_header = Table(
        [[Paragraph("<b>Earnings</b>", normal), Paragraph("<b>Amount (INR)</b>", right_align)]],
        colWidths=[380, 140]
    )
    earnings_header.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#e3f2fd')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bbdefb')),
    ]))
    elements.append(earnings_header)

    earnings_data = [
        [Paragraph("Basic Salary", normal),                  Paragraph(f"{float(payroll.basic_salary):,.2f}", right_align)],
        [Paragraph("House Rent Allowance (HRA)", normal),    Paragraph(f"{float(payroll.hra):,.2f}", right_align)],
        [Paragraph("Travel Allowance", normal),              Paragraph(f"{float(payroll.travel_allowance):,.2f}", right_align)],
        [Paragraph("Health Allowance", normal),              Paragraph(f"{float(payroll.health_allowance):,.2f}", right_align)],
        [Paragraph("Other Allowances", normal),              Paragraph(f"{float(payroll.allowances):,.2f}", right_align)],
        [Paragraph("Overtime Pay", normal),                  Paragraph(f"{float(payroll.overtime_pay):,.2f}", right_align)],
        [Paragraph("<b>Gross Salary</b>", normal),           Paragraph(f"<b>{float(payroll.gross_salary):,.2f}</b>", right_align)],
    ]
    earnings_table = Table(earnings_data, colWidths=[380, 140])
    earnings_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -2), 0.5, colors.HexColor('#eeeeee')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e8f5e9')),
        ('LINEABOVE', (0, -1), (-1, -1), 1, colors.HexColor('#43a047')),
    ]))
    elements.append(earnings_table)
    elements.append(Spacer(1, 8))

    # Deductions
    deductions_header = Table(
        [[Paragraph("<b>Deductions</b>", normal), Paragraph("<b>Amount (INR)</b>", right_align)]],
        colWidths=[380, 140]
    )
    deductions_header.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fce4ec')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#f48fb1')),
    ]))
    elements.append(deductions_header)

    deductions_data = [
        [Paragraph("LOP Deduction", normal),             Paragraph(f"-{float(payroll.lop_deduction):,.2f}", right_align)],
        [Paragraph("Advance Salary Recovery", normal),   Paragraph(f"-{float(payroll.advance_deduction):,.2f}", right_align)],
        [Paragraph("Other Deductions", normal),          Paragraph(f"-{float(payroll.deductions):,.2f}", right_align)],
    ]
    deductions_table = Table(deductions_data, colWidths=[380, 140])
    deductions_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#eeeeee')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fff8f8')),
    ]))
    elements.append(deductions_table)
    elements.append(Spacer(1, 6))

    # Net Salary
    net_table = Table(
        [[
            Paragraph("<b>Total Net Pay</b>", ParagraphStyle('NetLabel', parent=normal, fontSize=12)),
            Paragraph(f"<b>INR {float(payroll.net_salary):,.2f}</b>",
                      ParagraphStyle('NetAmount', parent=normal, fontSize=12, alignment=2, textColor=colors.HexColor('#1976d2')))
        ]],
        colWidths=[380, 140]
    )
    net_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#e3f2fd')),
        ('LINEABOVE', (0, 0), (-1, -1), 2, colors.HexColor('#1976d2')),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (0, -1), 8),
    ]))
    elements.append(net_table)

    elements.append(Spacer(1, 30))
    elements.append(Paragraph(
        "<font color='#999999' size='8'>This document is system-generated and is legally valid without a physical signature.</font>",
        normal
    ))

    #  Build & Stream 
    doc.build(elements)
    buffer.seek(0)

    safe_name = full_name.replace(" ", "_").lower()
    filename = f"payslip_{safe_name}_{salary_month_display.replace(' ', '_')}.pdf"

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )