import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy.future import select
from app.core.database import AsyncSessionLocal
from app.models.user import User, UserProfile, UserRole, UserStatus
from app.core.security import hash_password

async def create_super_admin():
    print(" Starting Super Admin provisioning script...")
    
    ADMIN_EMAIL = "admin@c51.com"
    ADMIN_PASSWORD = "c51@321"
    
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(select(User).where(User.email == ADMIN_EMAIL))
            existing_admin = result.scalars().first()
            
            if existing_admin:
                print(f" Account initialization skipped: '{ADMIN_EMAIL}' is already registered.")
                return

            print(f"Creating system account for {ADMIN_EMAIL}...")
            
            hashed_pwd = hash_password(ADMIN_PASSWORD)
            admin_user = User(
                email=ADMIN_EMAIL,
                hashed_password=hashed_pwd,
                role=UserRole.SUPER_ADMIN,
                status=UserStatus.ACTIVE
            )
            session.add(admin_user)
            await session.flush()  

            admin_profile = UserProfile(
                user_id=admin_user.id,
                first_name="System",
                last_name="Administrator",
                department="Office",
                employee_id="ADMIN001",
                designation="Super Admin"
            )
            session.add(admin_profile)
            
        print(f" Success! Super Admin account successfully created.")
        print(f" Email: {ADMIN_EMAIL}")
        print(f" Role: {UserRole.SUPER_ADMIN.value}")

if __name__ == "__main__":
    asyncio.run(create_super_admin())