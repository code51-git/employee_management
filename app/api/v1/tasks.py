from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func,delete
from uuid import UUID
from typing import Optional
from app.models.user import EmployeeTask, TaskStatus,UserProfile
from app.schemas.task import TaskCreate, TaskUpdate, TaskResponse,BulkDeletePayload
from app.core.database import get_db
from app.core.permissions import hr_and_admin, everyone 

router = APIRouter(prefix="/tasks", tags=["Employee Tasks"])

#  1. CREATE TASK (Admin/HR Only)
@router.post("/create", response_model=TaskResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(everyone)])
async def create_employee_task(payload: TaskCreate, db: AsyncSession = Depends(get_db)):
    prof_res = await db.execute(select(UserProfile).where(UserProfile.user_id == payload.user_id))
    profile = prof_res.scalars().first()
    
    if not profile:
        raise HTTPException(
            status_code=404, 
            detail=f"Employee profile linked to User ID '{payload.user_id}' not found."
        )

    # 2. Date safety validation guardrail
    if payload.task_end < payload.task_start:
        raise HTTPException(status_code=400, detail="Task end date cannot be earlier than the start date.")

    new_task = EmployeeTask(
        user_profile_id=profile.id,  
        task_name=payload.task_name,
        task_details=payload.task_details,
        task_start=payload.task_start,
        task_end=payload.task_end,
        status=payload.status.value if hasattr(payload.status, "value") else payload.status
    )
    
    db.add(new_task)
    await db.commit()
    await db.refresh(new_task)
    return TaskResponse.model_validate(new_task)


#  UPDATE TASK 
@router.patch("/update/{task_id}", response_model=TaskResponse)
async def update_employee_task(
    task_id: UUID, 
    payload: TaskUpdate, 
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = current_user.get("sub")
    caller_role = current_user.get("role")
    is_admin = caller_role in ["SUPER_ADMIN", "HR_ADMIN"]

    result = await db.execute(
        select(EmployeeTask).join(UserProfile).where(EmployeeTask.id == task_id)
    )
    task = result.scalars().first()

    if not task:
        raise HTTPException(status_code=404, detail="Task record not found.")

    update_data = payload.model_dump(exclude_unset=True)

    if not is_admin:
        prof_res = await db.execute(select(UserProfile).where(UserProfile.id == task.user_profile_id))
        profile = prof_res.scalars().first()
        
        if not profile or str(profile.user_id) != str(caller_id):
            raise HTTPException(status_code=403, detail="Not authorized to edit this task.")
        
        if any(k in update_data for k in ["task_name", "task_details", "task_start", "task_end"]):
            raise HTTPException(status_code=403, detail="Employees can only modify task status updates.")

    for key, value in update_data.items():
        setattr(task, key, value)

    if task.task_end < task.task_start:
        raise HTTPException(status_code=400, detail="Task end date cannot be earlier than the start date.")

    await db.commit()
    await db.refresh(task)
    return TaskResponse.model_validate(task)


#  LIST TASKS 
@router.get("/list")
async def list_employee_tasks(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    status_filter: Optional[TaskStatus] = Query(None, alias="status"),
    target_user_id: Optional[UUID] = Query(None, description="Admins can filter by a specific employee's user_id"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = current_user.get("sub")
    caller_role = current_user.get("role")
    is_admin = caller_role in ["SUPER_ADMIN", "HR_ADMIN"]

    base_query = select(EmployeeTask).join(UserProfile, EmployeeTask.user_profile_id == UserProfile.id)

    if not is_admin:
        base_query = base_query.where(UserProfile.user_id == caller_id)
    elif target_user_id:
        base_query = base_query.where(UserProfile.user_id == target_user_id)

    if status_filter:
        base_query = base_query.where(EmployeeTask.status == status_filter)

    count_query = select(func.count(EmployeeTask.id)).select_from(base_query.subquery())
    count_res = await db.execute(count_query)
    total_count = count_res.scalar() or 0

    offset = (page - 1) * size
    fetch_query = (
        base_query
        .order_by(EmployeeTask.created_at.desc(), EmployeeTask.id.desc()) 
        .offset(offset)
        .limit(size)
    )
    
    fetch_res = await db.execute(fetch_query)
    tasks = fetch_res.scalars().all()

    return {
        "total_count": total_count,
        "page": page,
        "size": size,
        "items": [TaskResponse.model_validate(t) for t in tasks]
    }

#delete
@router.delete("/delete/{task_id}", status_code=status.HTTP_200_OK)
async def delete_employee_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = current_user.get("sub")
    caller_role = current_user.get("role")
    is_admin = caller_role in ["SUPER_ADMIN", "HR_ADMIN"]

    result = await db.execute(
        select(EmployeeTask)
        .join(UserProfile)
        .where(EmployeeTask.id == task_id)
    )
    task = result.scalars().first()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Task record not found."
        )

    if not is_admin:
        prof_res = await db.execute(
            select(UserProfile).where(UserProfile.id == task.user_profile_id)
        )
        profile = prof_res.scalars().first()
        
        if not profile or str(profile.user_id) != str(caller_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. You can only delete tasks assigned to yourself."
            )

    await db.delete(task)
    await db.commit()

    return {
        "message": "Task deleted successfully.",
        "task_id": task_id
    }


#bulk delete
@router.post("/bulk-delete", status_code=status.HTTP_200_OK)
async def bulk_delete_employee_tasks(
    payload: BulkDeletePayload,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    if not payload.task_ids:
        raise HTTPException(status_code=400, detail="The task_ids list cannot be empty.")

    caller_id = current_user.get("sub")
    caller_role = current_user.get("role")
    is_admin = caller_role in ["SUPER_ADMIN", "HR_ADMIN"]

    result = await db.execute(
        select(EmployeeTask)
        .join(UserProfile)
        .where(EmployeeTask.id.in_(payload.task_ids))
    )
    fetched_tasks = result.scalars().all()

    if not fetched_tasks:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="None of the specified tasks were found."
        )

    if not is_admin:
        for task in fetched_tasks:
            prof_res = await db.execute(
                select(UserProfile).where(UserProfile.id == task.user_profile_id)
            )
            profile = prof_res.scalars().first()
            
            if not profile or str(profile.user_id) != str(caller_id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied. One or more selected tasks belong to another employee."
                )

    matched_ids = [t.id for t in fetched_tasks]
    await db.execute(
        delete(EmployeeTask).where(EmployeeTask.id.in_(matched_ids))
    )
    await db.commit()

    return {
        "message": f"Successfully deleted {len(matched_ids)} task(s).",
        "requested_ids_count": len(payload.task_ids),
        "deleted_ids_count": len(matched_ids),
        "deleted_task_ids": matched_ids
    }