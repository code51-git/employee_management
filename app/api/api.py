from fastapi import APIRouter
from app.api.v1 import auth ,users ,meetings,holidays,leaves,bills,payroll,admin_leave_balances,overtime,chat,chat_ws,payroll_pdf

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(meetings.router)
api_router.include_router(holidays.router)
api_router.include_router(leaves.router)
api_router.include_router(bills.router)
api_router.include_router(payroll.router)
api_router.include_router(admin_leave_balances.router)
api_router.include_router(overtime.router)
api_router.include_router(chat.router)
api_router.include_router(chat_ws.router)
api_router.include_router(payroll_pdf.router)
