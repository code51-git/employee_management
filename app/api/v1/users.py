import secrets
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks,Query,Response,Body,Form,File,UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from app.core.database import get_db
from app.core.permissions import hr_and_admin,everyone,admin_only
from app.core.security import hash_password
from app.models.user import User, UserProfile, UserRole, UserStatus,EmployeeBankDetails,EmployeeDocument
from app.schemas.user import UserRegister
from app.schemas.user_profile import UserProfileResponse,UserProfileRegister,UserListResponse,UserProfileUpdate
from app.services.email import send_welcome_email
from sqlalchemy.orm import selectinload
import os
import aioboto3
from typing import List
import uuid


router = APIRouter(prefix="/users", tags=["User Profiles & Management"])
UPLOAD_DIR = "static/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

#LIST
@router.get("/list", response_model=UserListResponse, dependencies=[Depends(hr_and_admin)])
async def list_employees(
    page: int = Query(1, ge=1, description="Page number to fetch"),
    size: int = Query(10, ge=1, le=100, description="Number of items per page"),
    search: str | None = Query(None, description="Search by First Name, Last Name, or Employee ID"),
    department: str | None = Query(None, description="Filter specifically by Department name"),
    db: AsyncSession = Depends(get_db)
):

    base_query = select(User).join(UserProfile)
    
    if search:
        search_filter = f"%{search}%"
        base_query = base_query.where(
            (UserProfile.first_name.ilike(search_filter)) |
            (UserProfile.last_name.ilike(search_filter)) |
            (UserProfile.employee_id.ilike(search_filter))
        )
        
    if department:
        base_query = base_query.where(UserProfile.department.ilike(f"%{department}%"))

    count_query = select(func.count(func.distinct(User.id))).select_from(base_query.subquery())
    count_result = await db.execute(count_query)
    total_count = count_result.scalar() or 0

    offset = (page - 1) * size
    fetch_query = (
        base_query
        .options(
            selectinload(User.profile).selectinload(UserProfile.bank_details),
            selectinload(User.profile).selectinload(UserProfile.documents)
        )
        .order_by(UserProfile.employee_id.asc())
        .offset(offset)
        .limit(size)
    )
    
    fetch_result = await db.execute(fetch_query)
    users = fetch_result.scalars().all()

    total_pages = (total_count + size - 1) // size if total_count > 0 else 0

    return {
        "total_count": total_count,
        "page": page,
        "size": size,
        "total_pages": total_pages,
        "items": users
    }


#CREATE
@router.post("/create", response_model=UserProfileResponse, dependencies=[Depends(hr_and_admin)])
async def provision_employee(
    payload: UserProfileRegister,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.email == payload.email))
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="Account email already exists.")
        
    id_check = await db.execute(select(UserProfile).where(UserProfile.employee_id == payload.employee_id))
    if id_check.scalars().first():
        raise HTTPException(status_code=400, detail="Employee ID number is already assigned.")

    temp_password = secrets.token_urlsafe(10)
    new_user = User(
        email=payload.email,
        hashed_password=hash_password(temp_password),
        role=UserRole.USER,
        status=UserStatus.ACTIVE
    )
    db.add(new_user)
    await db.flush()

    new_profile = UserProfile(
        user_id=new_user.id,
        employee_id=payload.employee_id,
        employee_type=payload.employee_type,
        first_name=payload.first_name,
        last_name=payload.last_name,
        company_email=payload.company_email,
        phone_number=payload.phone_number,
        whatsapp_number=payload.whatsapp_number,
        address=payload.address,
        department=payload.department,
        designation=payload.designation,
        date_of_joining=payload.date_of_joining,
        total_industry_experience=payload.total_industry_experience,
        basic_salary=getattr(payload, 'basic_salary', 0.00)
    )
    db.add(new_profile)
    await db.commit()

    new_user.profile = new_profile

    background_tasks.add_task(
        send_welcome_email, 
        email_to=new_user.email, 
        password=temp_password, 
        first_name=new_profile.first_name
    )

    return new_user

#PROFILE
@router.get("/profile", response_model=UserProfileResponse)
async def get_user_profile(
    employee_id: str | None = Query(None, description="HR/Admins can provide an Employee ID to search for records"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):

    caller_id = current_user.get("sub")
    caller_role = current_user.get("role")

    if employee_id:
        if caller_role not in [UserRole.SUPER_ADMIN.value, UserRole.HR_ADMIN.value]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. Only HR or Admins can search profiles by Employee ID."
            )
            
        result = await db.execute(
            select(User)
            .join(UserProfile)
            .where(UserProfile.employee_id == employee_id)
            # 🌟 NESTED LOADS: Pull profile extensions for admin searches
            .options(
                selectinload(User.profile).selectinload(UserProfile.bank_details),
                selectinload(User.profile).selectinload(UserProfile.documents)
            )
        )
        target_user = result.scalars().first()
        
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No employee record found matching ID '{employee_id}'"
            )
        return target_user

    result = await db.execute(
        select(User)
        .where(User.id == caller_id)
        .options(
            selectinload(User.profile).selectinload(UserProfile.bank_details),
            selectinload(User.profile).selectinload(UserProfile.documents)
        )
    )
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User account record missing."
        )
        
    return user

#UPDATE PROFILE

@router.patch("/update/{employee_id}", response_model=UserProfileResponse, dependencies=[Depends(hr_and_admin)])
async def update_employee_profile(
    employee_id: str,
    payload: UserProfileUpdate,
    db: AsyncSession = Depends(get_db)
):

    result = await db.execute(
        select(User)
        .join(UserProfile)
        .where(UserProfile.employee_id == employee_id)
        .options(selectinload(User.profile))
    )
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Employee with ID '{employee_id}' not found."
        )

    update_data = payload.model_dump(exclude_unset=True)

    account_fields = ["role", "status"]
    
    for key, value in update_data.items():
        if key in account_fields:
            setattr(user, key, value)
        else:
            setattr(user.profile, key, value)

    await db.commit()
    await db.refresh(user)  
    return user


# DELETE EMPLOYEE 
@router.delete("/delete/{employee_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(admin_only)])
async def terminate_and_delete_employee(
    employee_id: str,
    db: AsyncSession = Depends(get_db)
):
 
    result = await db.execute(
        select(User)
        .join(UserProfile)
        .where(UserProfile.employee_id == employee_id)
    )
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Employee with ID '{employee_id}' not found."
        )

    await db.delete(user)
    await db.commit()
    
    return Response(status_code=status.HTTP_204_NO_CONTENT)

#create hr - admin only
@router.post("/create-hr", response_model=UserProfileResponse, dependencies=[Depends(hr_and_admin)])
async def provision_hr_manager(
    payload: UserProfileRegister,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):

    result = await db.execute(select(User).where(User.email == payload.email))
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="Account email already exists.")
        
    id_check = await db.execute(select(UserProfile).where(UserProfile.employee_id == payload.employee_id))
    if id_check.scalars().first():
        raise HTTPException(status_code=400, detail="Employee ID number is already assigned.")

    temp_password = secrets.token_urlsafe(10)
    
    new_user = User(
        email=payload.email,
        hashed_password=hash_password(temp_password),
        role=UserRole.HR_ADMIN, 
        status=UserStatus.ACTIVE
    )
    db.add(new_user)
    await db.flush()  

    new_profile = UserProfile(
        user_id=new_user.id,
        employee_id=payload.employee_id,
        employee_type=payload.employee_type,
        first_name=payload.first_name,
        last_name=payload.last_name,
        company_email=payload.company_email,
        phone_number=payload.phone_number,
        whatsapp_number=payload.whatsapp_number,
        address=payload.address,
        department=payload.department,
        designation=payload.designation,
        date_of_joining=payload.date_of_joining,
        total_industry_experience=payload.total_industry_experience,
        basic_salary=getattr(payload, 'basic_salary', 0.00) 
    )
    db.add(new_profile)
    await db.commit()

    new_user.profile = new_profile

    background_tasks.add_task(
        send_welcome_email, 
        email_to=new_user.email, 
        password=temp_password, 
        first_name=new_profile.first_name
    )

    return new_user

#bank details upload
@router.post("/bank-setup")
async def admin_setup_bank_details(
    target_user_id: uuid.UUID = Body(...), 
    account_holder_name: str = Body(...),
    account_number: str = Body(...),
    bank_name: str = Body(...),
    ifsc_code: str = Body(...),
    branch_name: str = Body(None),
    db: AsyncSession = Depends(get_db)
):
    prof_res = await db.execute(select(UserProfile).where(UserProfile.user_id == target_user_id))
    profile = prof_res.scalars().first()
    
    if not profile:
        raise HTTPException(status_code=404, detail="Target employee profile contract not found.")

    existing_bank = await db.execute(select(EmployeeBankDetails).where(EmployeeBankDetails.user_profile_id == profile.id))
    bank_info = existing_bank.scalars().first()

    if bank_info:
        bank_info.account_holder_name = account_holder_name
        bank_info.account_number = account_number
        bank_info.bank_name = bank_name
        bank_info.ifsc_code = ifsc_code
        bank_info.branch_name = branch_name
        message = "Employee banking profile updated successfully."
    else:
        bank_info = EmployeeBankDetails(
            id=uuid.uuid4(),
            user_profile_id=profile.id,
            account_holder_name=account_holder_name,
            account_number=account_number,
            bank_name=bank_name,
            ifsc_code=ifsc_code,
            branch_name=branch_name
        )
        db.add(bank_info)
        message = "Employee banking profile recorded successfully."

    await db.commit()
    return {"message": message, "target_user_id": target_user_id}


# UPLOAD MULTIPLE KYC/RESUME DOCUMENTS FOR AN EMPLOYEE
@router.post("/upload-documents", status_code=status.HTTP_201_CREATED)
async def admin_upload_employee_documents(
    target_user_id: uuid.UUID = Form(...),
    document_types: List[str] = Form(...), 
    files: List[UploadFile] = File(...),   
    db: AsyncSession = Depends(get_db)
):
    if len(document_types) != len(files):
        raise HTTPException(status_code=400, detail="Mismatch between document types and files count.")

    # Load environment credentials
    cf_account_id = os.getenv("CF_R2_ACCOUNT_ID")
    cf_access_key = os.getenv("CF_R2_ACCESS_KEY_ID")
    cf_secret_key = os.getenv("CF_R2_SECRET_ACCESS_KEY")
    cf_bucket_name = os.getenv("CF_R2_BUCKET_NAME")
    cf_public_url = os.getenv("CF_R2_PUBLIC_URL")

    if not all([cf_account_id, cf_access_key, cf_secret_key, cf_bucket_name, cf_public_url]):
        raise HTTPException(status_code=500, detail="Cloud storage configuration error.")

    r2_endpoint_url = f"https://{cf_account_id}.r2.cloudflarestorage.com"

    # Locate the target employee profile
    prof_res = await db.execute(select(UserProfile).where(UserProfile.user_id == target_user_id))
    profile = prof_res.scalars().first()
    
    if not profile:
        raise HTTPException(status_code=404, detail="Employee target profile record missing.")

    uploaded_records = []

    session = aioboto3.Session()
    async with session.client(
        "s3",
        endpoint_url=r2_endpoint_url,
        aws_access_key_id=cf_access_key,
        aws_secret_access_key=cf_secret_key,
    ) as s3_client:

        for doc_type, file in zip(document_types, files):
            file_extension = os.path.splitext(file.filename)[1]
            unique_key = f"employees/{profile.id}/{uuid.uuid4().hex}_{doc_type.upper()}{file_extension}"
            
            file_data = await file.read()

            try:
                await s3_client.put_object(
                    Bucket=cf_bucket_name,
                    Key=unique_key,
                    Body=file_data,
                    ContentType=file.content_type
                )
            except Exception as cloud_err:
                raise HTTPException(status_code=500, detail=f"Cloudflare R2 upload failed: {str(cloud_err)}")

            final_public_url = f"{cf_public_url}/{unique_key}"

            new_doc = EmployeeDocument(
                id=uuid.uuid4(),
                user_profile_id=profile.id,
                document_type=doc_type.upper(),
                file_url=final_public_url
            )
            db.add(new_doc)
            uploaded_records.append(new_doc)

    await db.commit()

    return {
        "message": f"Successfully secured {len(uploaded_records)} assets in Cloudflare R2 for employee.",
        "target_user_id": target_user_id,
        "uploaded_documents": [
            {"document_type": d.document_type, "file_url": d.file_url} for d in uploaded_records
        ]
    }

#upload profile image
@router.post("/upload-avatar", status_code=status.HTTP_200_OK)
async def upload_employee_profile_image(
    target_user_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    """Streams a profile image directly into Cloudflare R2 and binds the CDN link to the employee record."""
    # Validate it's an image file format
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Uploaded file must be a valid image format (jpg/png).")

    # Load environmental storage connections
    cf_account_id = os.getenv("CF_R2_ACCOUNT_ID")
    cf_access_key = os.getenv("CF_R2_ACCESS_KEY_ID")
    cf_secret_key = os.getenv("CF_R2_SECRET_ACCESS_KEY")
    cf_bucket_name = os.getenv("CF_R2_BUCKET_NAME")
    cf_public_url = os.getenv("CF_R2_PUBLIC_URL")

    if not all([cf_account_id, cf_access_key, cf_secret_key, cf_bucket_name, cf_public_url]):
        raise HTTPException(status_code=500, detail="Cloud storage configuration error.")

    # Locate targeted profile record
    prof_res = await db.execute(select(UserProfile).where(UserProfile.user_id == target_user_id))
    profile = prof_res.scalars().first()
    
    if not profile:
        raise HTTPException(status_code=404, detail="Employee target profile record missing.")

    # Generate unique key path index destination path inside R2
    file_extension = os.path.splitext(file.filename)[1]
    unique_key = f"avatars/{profile.id}/avatar{file_extension}"
    r2_endpoint_url = f"https://{cf_account_id}.r2.cloudflarestorage.com"

    # Read binary payload
    file_data = await file.read()

    # Stream file to Cloudflare storage
    session = aioboto3.Session()
    async with session.client(
        "s3",
        endpoint_url=r2_endpoint_url,
        aws_access_key_id=cf_access_key,
        aws_secret_access_key=cf_secret_key,
    ) as s3_client:
        try:
            await s3_client.put_object(
                Bucket=cf_bucket_name,
                Key=unique_key,
                Body=file_data,
                ContentType=file.content_type
            )
        except Exception as cloud_err:
            raise HTTPException(status_code=500, detail=f"Cloudflare R2 avatar upload failed: {str(cloud_err)}")

    # Update profile entry link property field tracking 
    final_public_url = f"{cf_public_url}/{unique_key}"
    profile.profile_image_url = final_public_url
    
    await db.commit()

    return {
        "message": "Employee profile image updated successfully.",
        "target_user_id": target_user_id,
        "profile_image_url": final_public_url
    }
