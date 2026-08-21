import os
import uuid
import aioboto3
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Form, File, UploadFile, Path, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.models.user import UserProfile
from app.models.user import EmployeePayslip
from app.schemas.payslips import PayslipResponse, BulkPayslipUploadResponse
from app.core.database import get_db
from app.core.permissions import hr_and_admin, everyone

router = APIRouter(prefix="/api/v1/payslips", tags=["Payslips"])


# --- Helper Function for R2 Uploads ---
async def upload_file_to_r2(file_obj: UploadFile, folder_path: str) -> str:
    cf_account_id = os.getenv("CF_R2_ACCOUNT_ID")
    cf_access_key = os.getenv("CF_R2_ACCESS_KEY_ID")
    cf_secret_key = os.getenv("CF_R2_SECRET_ACCESS_KEY")
    cf_bucket_name = os.getenv("CF_R2_BUCKET_NAME")
    cf_public_url = os.getenv("CF_R2_PUBLIC_URL")

    if not all([cf_account_id, cf_access_key, cf_secret_key, cf_bucket_name, cf_public_url]):
        raise HTTPException(status_code=500, detail="Cloud storage credentials not configured.")

    ext = os.path.splitext(file_obj.filename)[1] or ".pdf"
    unique_key = f"payslips/{folder_path}/{uuid.uuid4()}{ext}"
    r2_endpoint = f"https://{cf_account_id}.r2.cloudflarestorage.com"

    file_data = await file_obj.read()
    session = aioboto3.Session()

    async with session.client(
        "s3",
        endpoint_url=r2_endpoint,
        aws_access_key_id=cf_access_key,
        aws_secret_access_key=cf_secret_key,
    ) as s3_client:
        try:
            await s3_client.put_object(
                Bucket=cf_bucket_name,
                Key=unique_key,
                Body=file_data,
                ContentType=file_obj.content_type
            )
        except Exception as err:
            raise HTTPException(status_code=500, detail=f"R2 Upload failed: {str(err)}")

    return f"{cf_public_url.rstrip('/')}/{unique_key}"


# -------------------------------------------------------------
# 1. BULK UPLOAD PAYSLIPS
# -------------------------------------------------------------
@router.post(
    "/bulk-upload",
    response_model=BulkPayslipUploadResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(hr_and_admin)]
)
async def bulk_upload_payslips(
    user_id: uuid.UUID = Form(..., description="The user UUID of the target employee"),
    title: Optional[str] = Form(None, description="Optional title or batch descriptor"),
    old_payslips: List[UploadFile] = File(default=[], description="List of previous/old payslip files"),
    new_payslips: List[UploadFile] = File(default=[], description="List of current/new payslip files"),
    db: AsyncSession = Depends(get_db)
):
    # Verify employee profile exists
    prof_res = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
    profile = prof_res.scalars().first()
    if not profile:
        raise HTTPException(status_code=404, detail="Employee user profile not found.")

    uploaded_records: List[EmployeePayslip] = []

    # Upload all old payslips
    for old_file in old_payslips:
        if old_file.filename:
            url = await upload_file_to_r2(old_file, f"{profile.id}/old")
            record = EmployeePayslip(
                id=uuid.uuid4(),
                user_profile_id=profile.id,
                title=title or old_file.filename,
                old_payslip_url=url,
                new_payslip_url=None
            )
            db.add(record)
            uploaded_records.append(record)

    # Upload all new payslips
    for new_file in new_payslips:
        if new_file.filename:
            url = await upload_file_to_r2(new_file, f"{profile.id}/new")
            record = EmployeePayslip(
                id=uuid.uuid4(),
                user_profile_id=profile.id,
                title=title or new_file.filename,
                old_payslip_url=None,
                new_payslip_url=url
            )
            db.add(record)
            uploaded_records.append(record)

    if not uploaded_records:
        raise HTTPException(status_code=400, detail="No valid files provided for upload.")

    await db.commit()
    for rec in uploaded_records:
        await db.refresh(rec)

    return {
        "message": "Payslips uploaded successfully.",
        "total_uploaded": len(uploaded_records),
        "payslips": uploaded_records
    }


# -------------------------------------------------------------
# 2. LIST PAYSLIPS BY EMPLOYEE
# -------------------------------------------------------------
@router.get(
    "/employee/{target_user_id}",
    response_model=List[PayslipResponse],
    status_code=status.HTTP_200_OK
)
async def get_employee_payslips(
    target_user_id: uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = str(current_user.get("sub"))
    caller_role = current_user.get("role")
    is_admin = caller_role in ["SUPER_ADMIN", "HR_ADMIN"]

    # Authorization guard: Employees can only check their own payslips
    if not is_admin and str(target_user_id) != caller_id:
        raise HTTPException(status_code=403, detail="Access denied. Cannot view another employee's payslips.")

    prof_res = await db.execute(select(UserProfile).where(UserProfile.user_id == target_user_id))
    profile = prof_res.scalars().first()
    if not profile:
        raise HTTPException(status_code=404, detail="Employee profile not found.")

    res = await db.execute(
        select(EmployeePayslip)
        .where(EmployeePayslip.user_profile_id == profile.id)
        .order_by(EmployeePayslip.uploaded_at.desc())
    )
    return res.scalars().all()


# -------------------------------------------------------------
# 3. EDIT / REPLACE SINGLE PAYSLIP FILE
# -------------------------------------------------------------
@router.patch(
    "/{payslip_id}",
    response_model=PayslipResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(hr_and_admin)]
)
async def update_payslip_record(
    payslip_id: uuid.UUID = Path(...),
    title: Optional[str] = Form(None),
    old_payslip: Optional[UploadFile] = File(None),
    new_payslip: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(EmployeePayslip).where(EmployeePayslip.id == payslip_id))
    payslip = res.scalars().first()
    if not payslip:
        raise HTTPException(status_code=404, detail="Payslip record not found.")

    if title is not None:
        payslip.title = title

    if old_payslip and old_payslip.filename:
        payslip.old_payslip_url = await upload_file_to_r2(old_payslip, f"{payslip.user_profile_id}/old")

    if new_payslip and new_payslip.filename:
        payslip.new_payslip_url = await upload_file_to_r2(new_payslip, f"{payslip.user_profile_id}/new")

    payslip.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(payslip)
    return payslip


# -------------------------------------------------------------
# 4. DELETE PAYSLIP RECORD
# -------------------------------------------------------------
@router.delete(
    "/{payslip_id}",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(hr_and_admin)]
)
async def delete_payslip_record(
    payslip_id: uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(EmployeePayslip).where(EmployeePayslip.id == payslip_id))
    payslip = res.scalars().first()
    if not payslip:
        raise HTTPException(status_code=404, detail="Payslip record not found.")

    await db.delete(payslip)
    await db.commit()
    return {"message": "Payslip record deleted successfully.", "deleted_id": payslip_id}