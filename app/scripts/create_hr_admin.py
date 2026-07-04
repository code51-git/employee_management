import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy.future import select
from app.core.database import AsyncSessionLocal
from app.models.user import User, UserProfile, UserRole, UserStatus
from app.core.security import hash_password

async def create_hr_admin():
    print("👥 Starting HR Admin provisioning script...")
    
    HR_EMAIL = "hr@c51.com"
    HR_PASSWORD = "hr@c51@321"  
    
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(select(User).where(User.email == HR_EMAIL))
            existing_hr = result.scalars().first()
            
            if existing_hr:
                print(f"⚠️ Account initialization skipped: '{HR_EMAIL}' is already registered.")
                return

            print(f"Creating system account for {HR_EMAIL}...")
            
            hashed_pwd = hash_password(HR_PASSWORD)
            hr_user = User(
                email=HR_EMAIL,
                hashed_password=hashed_pwd,
                role=UserRole.HR_ADMIN,  
                status=UserStatus.ACTIVE
            )
            session.add(hr_user)
            await session.flush()  

            hr_profile = UserProfile(
                user_id=hr_user.id,
                first_name="Human",
                last_name="Resources",
                department="Talent Acquisition & Management",
                employee_id="HR001",
                designation="HR Manager",
                employee_type="Full-Time",
                basic_salary=0.00,
            )
            session.add(hr_profile)
            
        print(f"🎉 Success! HR Admin account successfully created.")
        print(f"📧 Email: {HR_EMAIL}")
        print(f"🔑 Role: {UserRole.HR_ADMIN.value}")

if __name__ == "__main__":
    asyncio.run(create_hr_admin())