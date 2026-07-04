from datetime import date
from dateutil.relativedelta import relativedelta

def format_experience_string(start_date: date) -> str:

    if not start_date:
        return "0 years 0 months 0 days"
        
    diff = relativedelta(date.today(), start_date)
    
    y_label = "year" if diff.years == 1 else "years"
    m_label = "month" if diff.months == 1 else "months"
    d_label = "day" if diff.days == 1 else "days"
    
    return f"{diff.years} {y_label} {diff.months} {m_label} {diff.days} {d_label}"