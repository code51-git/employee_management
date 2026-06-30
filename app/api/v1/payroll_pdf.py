import uuid
import os
from io import BytesIO
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_db
from app.core.permissions import everyone
from app.models.user import Payroll  
from app.models.user import User

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
    """Fetches a specific payroll record and streams a dynamically generated PDF statement with a corporate logo."""
    
    # 1. Fetch data from database
    query = select(Payroll, User).join(User, Payroll.user_id == User.id).where(Payroll.id == payroll_id)
    result = await db.execute(query)
    record = result.first()
    
    if not record:
        raise HTTPException(status_code=404, detail="Requested payroll document was not found.")
    
    payroll, employee = record

    # Security Boundary Check
    caller_id = current_user.get("sub")
    caller_role = current_user.get("role")
    if caller_role not in ["super_admin", "hr_admin"] and str(payroll.user_id) != str(caller_id):
        raise HTTPException(status_code=403, detail="Permission Denied: Unauthorized access to this pay stub.")

    # 2. Setup Memory Buffer and Templates
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40
    )
    
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'DocTitle', parent=styles['Heading1'], fontSize=20, leading=24,
        textColor=colors.HexColor('#1976d2'), alignment=0
    )
    section_heading = ParagraphStyle(
        'SectionHeading', parent=styles['Heading3'], fontSize=12, leading=16,
        textColor=colors.HexColor('#333333'), spaceBefore=15, spaceAfter=8
    )
    normal_style = styles['Normal']
    right_align_style = ParagraphStyle('RightAlign', parent=styles['Normal'], alignment=2)

    elements = []

    # 3. Logo Header Layout Logic
    logo_path = "app/static/logo.png"
    header_data = []
    
    if os.path.exists(logo_path):
        company_logo = Image(logo_path, width=100, height=40)
        header_data = [[Paragraph("OFFICIAL PAYSLIP SUMMARY", title_style), company_logo]]
    else:
        header_data = [[Paragraph("OFFICIAL PAYSLIP SUMMARY", title_style), Paragraph("<b>[Company Logo]</b>", normal_style)]]
    
    header_table = Table(header_data, colWidths=[380, 140])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
    ]))
    elements.append(header_table)
    
    # Divider Line
    divider = Table([[""]], colWidths=[520])
    divider.setStyle(TableStyle([('LINEBELOW', (0,0), (-1,-1), 1, colors.HexColor('#1976d2'))]))
    elements.append(divider)
    elements.append(Spacer(1, 15))

    # Resolve Employee Name safely
    full_name = getattr(employee, "name", None) or getattr(employee, "username", None)
    if not full_name and hasattr(employee, "first_name"):
        full_name = f"{employee.first_name} {getattr(employee, 'last_name', '')}".strip()
    if not full_name:
        full_name = "Employee Account"

    # Meta Information Table using your real `generated_at` column
    meta_data = [
        [Paragraph(f"<b>Employee Name:</b> {full_name}", normal_style), 
         Paragraph(f"<b>Pay Slip ID:</b> {str(payroll.id)[:8].upper()}", normal_style)],
        [Paragraph(f"<b>Employee Email:</b> {employee.email}", normal_style), 
         Paragraph(f"<b>Generated At:</b> {payroll.generated_at.strftime('%Y-%m-%d')}", normal_style)],
        [Paragraph(f"<b>Period Start:</b> {payroll.pay_period_start}", normal_style), 
         Paragraph(f"<b>Period End:</b> {payroll.pay_period_end}", normal_style)]
    ]
    
    meta_table = Table(meta_data, colWidths=[260, 260])
    meta_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    elements.append(meta_table)
    
    # Attendance & Leave Summary Section
    elements.append(Paragraph("<b>Attendance & Leave Summary</b>", section_heading))
    attendance_data = [
        [Paragraph("<b>Total Leave Days Taken</b>", normal_style), Paragraph(str(payroll.total_leave_days), right_align_style),
         Paragraph("<b>Loss of Pay (LOP) Days</b>", normal_style), Paragraph(str(payroll.lop_days), right_align_style)]
    ]
    attendance_table = Table(attendance_data, colWidths=[150, 110, 150, 110])
    attendance_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#dddddd')),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elements.append(attendance_table)

    # 4. Financial Breakdown Matrix Table using your real model names
    elements.append(Paragraph("<b>Earnings & Deductions Breakdown</b>", section_heading))
    
    financial_data = [
        [Paragraph("<b>Description Item</b>", normal_style), Paragraph("<b>Amount (INR)</b>", right_align_style)],
        [Paragraph("Basic Fixed Component Salary", normal_style), Paragraph(f"{payroll.basic_salary:.2f}", right_align_style)],
        [Paragraph("Overtime (OT) Pay Credit", normal_style), Paragraph(f"{payroll.overtime_pay:.2f}", right_align_style)],
        [Paragraph("Allowances Credit", normal_style), Paragraph(f"{payroll.allowances:.2f}", right_align_style)],
        [Paragraph("Loss of Pay (LOP) Deductions", normal_style), Paragraph(f"-{payroll.lop_deduction:.2f}", right_align_style)],
        [Paragraph("Advance Salary Deductions Balance Recovery", normal_style), Paragraph(f"-{payroll.advance_deduction:.2f}", right_align_style)],
        [Paragraph("Standard Regular Deductions", normal_style), Paragraph(f"-{payroll.deductions:.2f}", right_align_style)],
        [Paragraph("<b>Total Net Pay Distributed</b>", normal_style), Paragraph(f"<b>{payroll.net_salary:.2f}</b>", right_align_style)]
    ]
    
    fin_table = Table(financial_data, colWidths=[380, 140])
    fin_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f5f5f5')),
        ('GRID', (0,0), (-1,-2), 0.5, colors.HexColor('#cccccc')),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#e3f2fd')), # Highlights Net Salary Row
        ('LINEABOVE', (0,-1), (-1,-1), 1.5, colors.HexColor('#1976d2')),
    ]))
    elements.append(fin_table)
    
    elements.append(Spacer(1, 35))
    elements.append(Paragraph("<font color='#777777' size='8.5'>This document is system-generated and legally valid within the ecosystem registry without a physical signature requirement.</font>", normal_style))

    # 5. Compile document
    doc.build(elements)
    
    # 6. Rewind stream cursor and return streaming file download
    buffer.seek(0)
    safe_file_suffix = full_name.replace(" ", "_").lower()
    filename = f"payslip_{safe_file_suffix}_{payroll.pay_period_start}.pdf"
    
    return StreamingResponse(
        buffer, 
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )