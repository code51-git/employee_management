from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID
from typing import Optional,List
from app.models.user import TaskStatus

class TaskBase(BaseModel):
    task_name: str = Field(..., max_length=255, example="Prepare Payroll Report")
    task_details: str = Field(..., example="Complete and review the task details.")
    task_start: datetime
    task_end: datetime
    status: TaskStatus = TaskStatus.PENDING

class TaskCreate(TaskBase):
    user_id: UUID


class TaskUpdate(BaseModel):
    task_name: Optional[str] = Field(None, max_length=255)
    task_details: Optional[str] = None
    task_start: Optional[datetime] = None
    task_end: Optional[datetime] = None
    status: Optional[TaskStatus] = None


class TaskResponse(TaskBase):
    id: UUID
    user_profile_id: UUID
    created_at: datetime
    updated_at: datetime
    task_duration: str  

    class Config:
        from_attributes = True

    @classmethod
    def model_validate(cls, obj, **kwargs):
        start_time_str = obj.task_start.strftime("%I:%M %p")
        end_time_str = obj.task_end.strftime("%I:%M %p")
        
        delta = obj.task_end - obj.task_start
        days = delta.days
        hours = delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60

        duration_parts = []
        if days > 0:
            duration_parts.append(f"{days} day{'s' if days > 1 else ''}")
        if hours > 0:
            duration_parts.append(f"{hours} hr{'s' if hours > 1 else ''}")
        if minutes > 0 or not duration_parts:
            duration_parts.append(f"{minutes} min{'s' if minutes > 1 else ''}")
            
        total_duration = ", ".join(duration_parts)

        final_duration_string = f"{start_time_str} to {end_time_str} ({total_duration})"

        data = {
            "id": obj.id,
            "user_profile_id": obj.user_profile_id,
            "task_name": obj.task_name,
            "task_details": obj.task_details,
            "task_start": obj.task_start,
            "task_end": obj.task_end,
            "status": obj.status,
            "created_at": obj.created_at,
            "updated_at": obj.updated_at,
            "task_duration": final_duration_string
        }

        return cls(**data)
    

class BulkDeletePayload(BaseModel):
    task_ids: List[UUID]