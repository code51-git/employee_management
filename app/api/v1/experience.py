import os
import uuid
import boto3
from botocore.config import Config
from fastapi import APIRouter, Depends, HTTPException, Form, File, UploadFile, status,Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from uuid import UUID
from typing import Optional 
from app.models.user import PreviousCompanyDetail
from app.models.user import UserProfile
from app.core.database import get_db
from app.core.permissions import hr_and_admin, everyone

router = APIRouter()

@router.post("/experience/add", status_code=status.HTTP_201_CREATED)
async def add_previous_company_details(
    company_name: str = Form(...),
    company_role: str = Form(...),
    experience_years: str = Form(...),
    reason_for_leaving: str = Form(...),
    hr_contact_number: str = Form(None),
    
    documents: List[UploadFile] = File(None),
    
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = current_user.get("sub")

    prof_res = await db.execute(select(UserProfile).where(UserProfile.user_id == caller_id))
    profile = prof_res.scalars().first()
    if not profile:
        raise HTTPException(status_code=404, detail="Employee Profile not found.")

    cf_account_id = os.getenv("CF_R2_ACCOUNT_ID")
    cf_access_key = os.getenv("CF_R2_ACCESS_KEY_ID")
    cf_secret_key = os.getenv("CF_R2_SECRET_ACCESS_KEY")
    cf_bucket_name = os.getenv("CF_R2_BUCKET_NAME")
    cf_public_url = os.getenv("CF_R2_PUBLIC_URL")

    if not all([cf_account_id, cf_access_key, cf_secret_key, cf_bucket_name, cf_public_url]):
        raise HTTPException(status_code=500, detail="Cloud storage configuration error.")

    s3_client = boto3.client(
        "s3",
        endpoint_url=f"https://{cf_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=cf_access_key,
        aws_secret_access_key=cf_secret_key,
        config=Config(signature_version="s3v4")
    )

    uploaded_doc_urls = []

    try:
        if documents:
            for doc in documents:
                if doc.filename:
                    ext = doc.filename.split(".")[-1].lower() if "." in doc.filename else "dat"
                    key = f"experience_docs/{uuid.uuid4()}.{ext}"
                    content = await doc.read()
                    
                    s3_client.put_object(
                        Bucket=cf_bucket_name,
                        Key=key,
                        Body=content,
                        ContentType=doc.content_type
                    )
                    uploaded_doc_urls.append(f"{cf_public_url.rstrip('/')}/{key}")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload experience assets to R2: {str(e)}"
        )

    new_exp = PreviousCompanyDetail(
        id=uuid.uuid4(),
        user_profile_id=profile.id,
        company_name=company_name,
        comapany_role=company_role,
        experience_years=experience_years,
        reason_for_leaving=reason_for_leaving,
        hr_contact_number=hr_contact_number,
        company_document_urls=uploaded_doc_urls  
    )
    
    db.add(new_exp)
    await db.commit()
    
    return {
        "message": "Previous company experience record updated successfully.",
        "record_id": new_exp.id,
        "company_document_urls": uploaded_doc_urls
    }

#list

@router.get("/experience/list", status_code=status.HTTP_200_OK)
async def list_previous_company_details(
    target_user_id: Optional[UUID] = Query(None, description="Admins can specify a worker's user_id filter"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = current_user.get("sub")
    caller_role = current_user.get("role")
    is_admin = caller_role in ["SUPER_ADMIN", "HR_ADMIN"]

    query = select(PreviousCompanyDetail).join(UserProfile, PreviousCompanyDetail.user_profile_id == UserProfile.id)

    if not is_admin:
        query = query.where(UserProfile.user_id == caller_id)
    elif target_user_id:
        query = query.where(UserProfile.user_id == target_user_id)

    res = await db.execute(query)
    records = res.scalars().all()

    return {
        "count": len(records),
        "items": [
            {
                "id": r.id,
                "user_profile_id": r.user_profile_id,
                "company_name": r.company_name,
                "experience_years": r.experience_years,
                "reason_for_leaving": r.reason_for_leaving,
                "hr_contact_number": r.hr_contact_number,
                "company_document_urls": r.company_document_urls or []
            } for r in records
        ]
    }

#update
@router.put("/experience/update/{record_id}", status_code=status.HTTP_200_OK)
async def update_previous_company_details(
    record_id: UUID,
    company_name: Optional[str] = Form(None),
    experience_years: Optional[str] = Form(None),
    reason_for_leaving: Optional[str] = Form(None),
    hr_contact_number: Optional[str] = Form(None),
    # 📑 Optional slot to append additional files to this company block
    new_documents: List[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = current_user.get("sub")
    caller_role = current_user.get("role")
    is_admin = caller_role in ["SUPER_ADMIN", "HR_ADMIN"]

    result = await db.execute(
        select(PreviousCompanyDetail).where(PreviousCompanyDetail.id == record_id)
    )
    record = result.scalars().first()
    if not record:
        raise HTTPException(status_code=404, detail="Experience record not found.")

    prof_res = await db.execute(select(UserProfile).where(UserProfile.id == record.user_profile_id))
    profile = prof_res.scalars().first()
    
    if not is_admin and (not profile or str(profile.user_id) != str(caller_id)):
        raise HTTPException(status_code=403, detail="Access denied. You can only update your own records.")

    if company_name is not None: record.company_name = company_name
    if experience_years is not None: record.experience_years = experience_years
    if reason_for_leaving is not None: record.reason_for_leaving = reason_for_leaving
    if hr_contact_number is not None: record.hr_contact_number = hr_contact_number

    if new_documents and any(doc.filename for doc in new_documents):
        cf_account_id = os.getenv("CF_R2_ACCOUNT_ID")
        cf_access_key = os.getenv("CF_R2_ACCESS_KEY_ID")
        cf_secret_key = os.getenv("CF_R2_SECRET_ACCESS_KEY")
        cf_bucket_name = os.getenv("CF_R2_BUCKET_NAME")
        cf_public_url = os.getenv("CF_R2_PUBLIC_URL")

        s3_client = boto3.client(
            "s3",
            endpoint_url=f"https://{cf_account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=cf_access_key,
            aws_secret_access_key=cf_secret_key,
            config=Config(signature_version="s3v4")
        )

        current_urls = list(record.company_document_urls) if record.company_document_urls else []

        try:
            for doc in new_documents:
                if doc.filename:
                    ext = doc.filename.split(".")[-1].lower() if "." in doc.filename else "dat"
                    key = f"experience_docs/{uuid.uuid4()}.{ext}"
                    content = await doc.read()
                    
                    s3_client.put_object(
                        Bucket=cf_bucket_name, Key=key, Body=content, ContentType=doc.content_type
                    )
                    current_urls.append(f"{cf_public_url.rstrip('/')}/{key}")
            
            record.company_document_urls = current_urls
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Attachment processing fail: {str(e)}")

    await db.commit()
    await db.refresh(record)
    return {"message": "Record patched successfully.", "updated_document_urls": record.company_document_urls}

#delete
@router.delete("/experience/delete/{record_id}", status_code=status.HTTP_200_OK)
async def delete_previous_company_detail(
    record_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = current_user.get("sub")
    caller_role = current_user.get("role")
    is_admin = caller_role in ["SUPER_ADMIN", "HR_ADMIN"]

    result = await db.execute(
        select(PreviousCompanyDetail).where(PreviousCompanyDetail.id == record_id)
    )
    record = result.scalars().first()
    if not record:
        raise HTTPException(status_code=404, detail="Experience record target not found.")

    prof_res = await db.execute(select(UserProfile).where(UserProfile.id == record.user_profile_id))
    profile = prof_res.scalars().first()

    if not is_admin and (not profile or str(profile.user_id) != str(caller_id)):
        raise HTTPException(status_code=403, detail="Permission Denied. Cannot delete another user's metrics.")

    await db.delete(record)
    await db.commit()

    return {
        "message": "Previous company history record deleted successfully.",
        "record_id": record_id
    }