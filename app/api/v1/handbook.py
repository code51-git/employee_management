import os
import uuid
import boto3
from botocore.config import Config
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Optional

from app.core.database import get_db
from app.core.permissions import hr_and_admin, everyone
from app.models.announcement import Handbook
from app.schemas.handbook import HandbookResponse, HandbookListResponse,HandbookUpdate

router = APIRouter(prefix="/handbook", tags=["Employee Handbook"])

MAX_PDF_BYTES = 20 * 1024 * 1024  # 20 MB


@router.post("/upload", response_model=HandbookResponse, dependencies=[Depends(hr_and_admin)])
async def upload_handbook(
    title: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(hr_and_admin),
):
    if file.content_type != "application/pdf" or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF.")

    file_content = await file.read()
    if len(file_content) > MAX_PDF_BYTES:
        raise HTTPException(status_code=400, detail="Handbook PDF must be under 20 MB.")

    cf_account_id = os.getenv("CF_R2_ACCOUNT_ID")
    cf_access_key = os.getenv("CF_R2_ACCESS_KEY_ID")
    cf_secret_key = os.getenv("CF_R2_SECRET_ACCESS_KEY")
    cf_bucket_name = os.getenv("CF_R2_BUCKET_NAME")
    cf_public_url = os.getenv("CF_R2_PUBLIC_URL")

    if not all([cf_account_id, cf_access_key, cf_secret_key, cf_bucket_name, cf_public_url]):
        raise HTTPException(status_code=500, detail="Cloud storage configuration error.")

    try:
        unique_filename = f"handbooks/{uuid.uuid4()}.pdf"

        s3_client = boto3.client(
            "s3",
            endpoint_url=f"https://{cf_account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=cf_access_key,
            aws_secret_access_key=cf_secret_key,
            config=Config(signature_version="s3v4")
        )

        s3_client.put_object(
            Bucket=cf_bucket_name,
            Key=unique_filename,
            Body=file_content,
            ContentType=file.content_type
        )

        file_url = f"{cf_public_url.rstrip('/')}/{unique_filename}"

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload handbook to Cloudflare R2: {str(e)}"
        )

    # Deactivate previous handbooks so only one is "current"
    result = await db.execute(select(Handbook).where(Handbook.is_active == True))
    for old in result.scalars().all():
        old.is_active = False

    handbook = Handbook(
        id=uuid.uuid4(),
        title=title,
        file_url=file_url,
        is_active=True,
        uploaded_by=current_user.get("sub"),
    )
    db.add(handbook)
    await db.commit()
    await db.refresh(handbook)

    return handbook


@router.get("/current", response_model=HandbookResponse, dependencies=[Depends(everyone)])
async def get_current_handbook(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Handbook).where(Handbook.is_active == True).order_by(Handbook.uploaded_at.desc())
    )
    handbook = result.scalars().first()
    if not handbook:
        raise HTTPException(status_code=404, detail="No handbook uploaded yet.")
    return handbook


@router.get("/list", response_model=HandbookListResponse, dependencies=[Depends(hr_and_admin)])
async def list_handbooks(
    is_active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(Handbook)

    if is_active is not None:
        query = query.where(Handbook.is_active == is_active)

    query = query.order_by(Handbook.uploaded_at.desc())

    result = await db.execute(query)
    return {"items": result.scalars().all()}

#update

@router.patch("/{handbook_id}", response_model=HandbookResponse, dependencies=[Depends(hr_and_admin)])
async def update_handbook(
    handbook_id: uuid.UUID,
    payload: HandbookUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Handbook).where(Handbook.id == handbook_id))
    handbook = result.scalars().first()

    if not handbook:
        raise HTTPException(status_code=404, detail="Handbook not found.")

    update_data = payload.model_dump(exclude_unset=True)

    # If this one is being set active, deactivate all others first
    if update_data.get("is_active") is True:
        others = await db.execute(select(Handbook).where(Handbook.id != handbook_id))
        for other in others.scalars().all():
            other.is_active = False

    for key, value in update_data.items():
        setattr(handbook, key, value)

    await db.commit()
    await db.refresh(handbook)

    return handbook