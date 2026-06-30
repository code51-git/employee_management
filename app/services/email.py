import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.core.config import settings

def send_welcome_email(email_to: str, password: str, first_name: str):

    message = MIMEMultipart("alternative")
    message["Subject"] = "Welcome! Your Employee Account Credentials"
    message["From"] = settings.EMAILS_FROM
    message["To"] = email_to

    # HTML Email Template
    html_content = f"""
    <html>
        <body>
            <h3>Welcome to the Team, {first_name}!</h3>
            <p>An official corporate profile has been provisioned for you by Human Resources.</p>
            <p><strong>Login Portal Credentials:</strong></p>
            <ul>
                <li><strong>Email ID:</strong> {email_to}</li>
                <li><strong>Temporary Password:</strong> {password}</li>
            </ul>
            <p style="color: red;"> For security compliance, please update your password immediately after logging in.</p>
        </body>
    </html>
    """
    
    message.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls()  
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.EMAILS_FROM, email_to, message.as_string())
        print(f"📧 Core Dispatcher: Welcome email successfully dispatched to {email_to}")
    except Exception as e:
        print(f"❌ Core Dispatcher Email Failure: {str(e)}")


def send_leave_status_email(recipient_email: str, employee_name: str, leave_type: str, start_date: str, end_date: str, review_status: str):

    if not getattr(settings, "SMTP_HOST", None):
        print(f"✉️ SMTP Config missing. Mock Mail to {recipient_email}: Leave {review_status.upper()}")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Leave Application Status: {review_status.capitalize()}"
    msg["From"] = f"HR Department <{settings.SMTP_USER}>"
    msg["To"] = recipient_email

    status_color = "#2e7d32" if review_status.lower() == "approved" else "#c62828"

    html_content = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
            <div style="max-width: 600px; margin: 0 auto; border: 1px solid #e0e0e0; padding: 20px; border-radius: 8px;">
                <h2 style="color: #1976d2;">Leave Application Update</h2>
                <p>Hello <strong>{employee_name}</strong>,</p>
                <p>Your leave application request has been reviewed by the HR administration team.</p>
                
                <div style="background-color: #f9f9f9; padding: 15px; border-left: 4px solid {status_color}; margin: 20px 0;">
                    <p style="margin: 5px 0;"><strong>Type:</strong> {leave_type}</p>
                    <p style="margin: 5px 0;"><strong>Duration:</strong> {start_date} to {end_date}</p>
                    <p style="margin: 5px 0;"><strong>Status:</strong> <span style="color: {status_color}; font-weight: bold; text-transform: uppercase;">{review_status}</span></p>
                </div>

                <p>If you have any questions regarding this update, please reach out to your reporting manager or the HR operations desk.</p>
                <br>
                <hr style="border: 0; border-top: 1px solid #e0e0e0;">
                <p style="font-size: 12px; color: #777;">This is an automated system notification. Please do not reply directly to this email.</p>
            </div>
        </body>
    </html>
    """
    
    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls() 
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)  
            
            server.sendmail(settings.EMAILS_FROM, recipient_email, msg.as_string())
            
        print(f"✉️ Leave confirmation email sent successfully to {recipient_email}")
    except Exception as e:
        print(f"❌ Failed to dispatch leave status email: {str(e)}")


def send_password_reset_otp_email(email_to: str, otp: str):
    message = MIMEMultipart("alternative")
    message["Subject"] = f"{otp} is your Password Recovery Verification Code"
    message["From"] = settings.EMAILS_FROM
    message["To"] = email_to

    html_content = f"""
    <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; border: 1px solid #e0e0e0; padding: 20px; border-radius: 8px;">
                <h2 style="color: #c62828;">Password Reset Request</h2>
                <p>We received a request to reset the password linked to your employee profile.</p>
                <p>Please enter this verification OTP code inside your application interface:</p>
                
                <div style="margin: 25px 0;">
                    <span style="font-size: 28px; font-weight: bold; letter-spacing: 4px; color: #333; background: #f9f9f9; padding: 10px 24px; border: 1px dashed #cccccc; border-radius: 4px; display: inline-block;">
                        {otp}
                    </span>
                </div>
                
                <p style="color: #777; font-size: 13px;">This code is strictly confidential and will expire in <strong>5 minutes</strong>. If you did not make this request, please safely ignore this email.</p>
                <br>
                <hr style="border: 0; border-top: 1px solid #e0e0e0;">
                <p style="font-size: 12px; color: #777;">This is an automated security system notification.</p>
            </div>
        </body>
    </html>
    """
    
    message.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls()  
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.EMAILS_FROM, email_to, message.as_string())
        print(f"📧 Core Dispatcher: Security OTP email successfully sent to {email_to}")
    except Exception as e:
        print(f"❌ Core Dispatcher OTP Email Failure: {str(e)}")


