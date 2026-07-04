import uuid
from datetime import datetime, date
from enum import Enum
from typing import Optional, List
from sqlalchemy import String, DateTime, Date, Numeric, ForeignKey, Enum as SQLEnum, Text, Time,Float,Integer,Column,Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.core.utils import format_experience_string
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

class UserRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    HR_ADMIN = "hr_admin"
    USER = "user"

class UserStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"

class LeaveStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class PayrollStatus(str, Enum):
    DRAFT = "draft"
    PAID = "paid"

class BillStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class AdvanceStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEDUCTED = "deducted"

#   CORE USER & ACCOUNT 
class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(SQLEnum(UserRole), default=UserRole.USER, index=True, nullable=False)
    status: Mapped[UserStatus] = mapped_column(SQLEnum(UserStatus), default=UserStatus.ACTIVE, nullable=False)
    is_deleted = mapped_column(Boolean, default=False)
    fcm_token: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    profile: Mapped["UserProfile"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    attendance_records: Mapped[List["Attendance"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    leave_requests: Mapped[List["Leave"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    payrolls: Mapped[List["Payroll"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    password_reset_otp = Column(String(6), nullable=True)
    otp_expires_at = Column(DateTime, nullable=True)

#  USER PROFILE  
class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    dob: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    gender: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    department: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    designation: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    date_of_joining: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    basic_salary: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    profile_image_url = Column(String, nullable=True)
    employee_id: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False) 
    employee_type: Mapped[str] = mapped_column(String(50), default="Full-Time", nullable=False) 
    company_email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    whatsapp_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True) 
    total_industry_experience: Mapped[Optional[float]] = mapped_column(Float, default=0.0, nullable=True)
    document_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    
    total_experience_start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    user: Mapped["User"] = relationship(back_populates="profile")
    bank_details = relationship("EmployeeBankDetails", back_populates="profile", uselist=False, cascade="all, delete-orphan")
    qualifications = relationship("EmployeeQualification", back_populates="profile", cascade="all, delete-orphan")
    documents = relationship("EmployeeDocument",back_populates="profile",cascade="all, delete-orphan")
    overtime_records = relationship("EmployeeOvertime", back_populates="profile", cascade="all, delete-orphan")
    @property
    def company_experience_years(self) -> str: 
        if not self.date_of_joining:
            return "0 years 0 months 0 days"
            
        return format_experience_string(self.date_of_joining)


#  ATTENDANCE MANAGEMENT  
class Attendance(Base):
    __tablename__ = "attendance"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    work_date: Mapped[date] = mapped_column(Date, default=date.today, index=True, nullable=False)
    clock_in: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    clock_out: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    total_hours: Mapped[Optional[float]] = mapped_column(nullable=True)

    user: Mapped["User"] = relationship(back_populates="attendance_records")


#   LEAVE MANAGEMENT 
class Leave(Base):
    __tablename__ = "leaves"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    duration_days: Mapped[str] = mapped_column(String(50), nullable=False)  
    leave_type: Mapped[str] = mapped_column(String(50), nullable=False)  
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[LeaveStatus] = mapped_column(SQLEnum(LeaveStatus), default=LeaveStatus.PENDING, nullable=False)
    
    user: Mapped["User"] = relationship(back_populates="leave_requests")


#   HOLIDAY CALENDAR 
class Holiday(Base):
    __tablename__ = "holiday_calendar"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    holiday_date: Mapped[date] = mapped_column(Date, unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    is_mandatory: Mapped[bool] = mapped_column(default=True, nullable=False)


# PAYROLL 
class Payroll(Base):
    __tablename__ = "payroll"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    pay_period_start: Mapped[date] = mapped_column(Date, nullable=False)
    pay_period_end: Mapped[date] = mapped_column(Date, nullable=False)
    
    # Financial Matrix Snapshots
    basic_salary: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    overtime_pay: Mapped[float] = mapped_column(Numeric(10, 2), default=0.0, nullable=False)
    allowances: Mapped[float] = mapped_column(Numeric(10, 2), default=0.0, nullable=False)
    
    total_leave_days: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    lop_days: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    lop_deduction: Mapped[float] = mapped_column(Numeric(10, 2), default=0.0, nullable=False)
    
    deductions: Mapped[float] = mapped_column(Numeric(10, 2), default=0.0, nullable=False)
    advance_deduction: Mapped[float] = mapped_column(Numeric(10, 2), default=0.0, nullable=False)
    net_salary: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    
    status: Mapped[PayrollStatus] = mapped_column(SQLEnum(PayrollStatus), default=PayrollStatus.DRAFT, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    user: Mapped["User"] = relationship(back_populates="payrolls")

#  MEETINGS
class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meeting_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    start_time: Mapped[Time] = mapped_column(Time, nullable=False)
    end_time: Mapped[Time] = mapped_column(Time, nullable=False)
    meeting_link: Mapped[Optional[str]] = mapped_column(String(512), nullable=True) 
    
    organizer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    

    attendee_ids: Mapped[list[uuid.UUID]] = mapped_column(sa.dialects.postgresql.ARRAY(sa.UUID), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

# Bills 
class BillRequest(Base):
    __tablename__ = "bill_requests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)  
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attachment_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True) 
    spent_date: Mapped[date] = mapped_column(Date, nullable=False, doc="The day the transaction occurred")
    status: Mapped[BillStatus] = mapped_column(SQLEnum(BillStatus), default=BillStatus.PENDING, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    user: Mapped["User"] = relationship()

#advance salary
class AdvanceSalaryRequest(Base):
    __tablename__ = "advance_salary_requests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    amount_requested: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    target_repayment_month: Mapped[date] = mapped_column(Date, nullable=False) # e.g., 2026-07-01 to deduct in July
    
    status: Mapped[AdvanceStatus] = mapped_column(SQLEnum(AdvanceStatus), default=AdvanceStatus.PENDING, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    user: Mapped["User"] = relationship()


#leave balance
class EmployeeLeaveBalance(Base):
    __tablename__ = "employee_leave_balances"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    year: Mapped[int] = mapped_column(Integer, default=2026)
    
    casual_leaves_remaining: Mapped[float] = mapped_column(Numeric(4, 1), default=6.0)
    sick_leaves_remaining: Mapped[float] = mapped_column(Numeric(4, 1), default=12.0)

#empl bank
class EmployeeBankDetails(Base):
    __tablename__ = "employee_bank_details"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_profile_id = Column(UUID(as_uuid=True), ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False, unique=True)
    account_holder_name = Column(String, nullable=False)
    account_number = Column(String, nullable=False)
    bank_name = Column(String, nullable=False)
    ifsc_code = Column(String, nullable=False) 
    branch_name = Column(String, nullable=True)

    profile = relationship("UserProfile", back_populates="bank_details")


#emp qualification
class EmployeeQualification(Base):
    __tablename__ = "employee_qualifications"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_profile_id = Column(UUID(as_uuid=True), ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    degree_name = Column(String, nullable=False) 
    institution = Column(String, nullable=False) 
    passing_year = Column(Integer, nullable=False)
    percentage_or_cgpa = Column(String, nullable=False)

    profile = relationship("UserProfile", back_populates="qualifications")

#empl doc
class EmployeeDocument(Base):
    __tablename__ = "employee_documents"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_profile_id = Column(UUID(as_uuid=True), ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    document_type = Column(String, nullable=False) # 'PAN_CARD', 'AADHAAR_CARD', 'RESUME', 'PASSPORT'
    file_url = Column(String, nullable=False) 
    uploaded_at = Column(Date, default=date.today)

    profile = relationship("UserProfile", back_populates="documents")


class EmployeeOvertime(Base):
    __tablename__ = "employee_overtime"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_profile_id = Column(UUID(as_uuid=True), ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    date_worked = Column(Date, nullable=False)
    hours_worked = Column(Numeric(4, 2), nullable=False) 
    description = Column(String, nullable=True) 
    ot_rate = Column(Numeric(4, 2), nullable=False, default=1.00)
    ot_final_amount = Column(Numeric(12, 2), nullable=False, default=0.00)
    profile = relationship("UserProfile", back_populates="overtime_records")



