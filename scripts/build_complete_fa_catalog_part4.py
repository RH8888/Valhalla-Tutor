import json
from pathlib import Path

fa_path = Path("app/locales/fa.json")
with open(fa_path, "r", encoding="utf-8") as f:
    fa = json.load(f)

# Part 4: Management, Guidance, and Explanations
fa.update({
    "Individual Subject Score": "درصد درس اختصاصی",
    "Ineligible Students ()": "دانش‌آموزان غیرمجاز",
    "Key:": "کلید:",
    "Konkur / پشت کنکور": "پشت کنکوری / فارغ‌التحصیل",
    "LOCKED": "قفل‌شده",
    "Late": "با تاخیر",
    "Latest": "آخرین",
    "Latest Average": "آخرین میانگین",
    "Latest exam average": "میانگین آخرین آزمون",
    "Location / Address:": "محل / آدرس برگزاری:",
    "Location / Classroom Address": "محل برگزاری / آدرس کلاس",
    "Manage &bull; Configure &rarr;": "مدیریت &bull; تنظیمات &larr;",
    "Manage &rarr;": "مدیریت &larr;",
    "Manage Series &rarr;": "مدیریت سری آزمون &larr;",
    "Manage Track &rarr;": "مدیریت رشته &larr;",
    "Manage predefined and custom study tracks and their curriculum subjects.": "مدیریت رشته‌های پیش‌فرض و سفارشی و دروس آموزشی هر رشته.",
    "Manage recurring availability, student meeting slots, and calendar events.": "مدیریت زمان‌های در دسترس، بازه‌های جلسات و رویدادهای تقویم.",
    "Manage recurring occurrences, mark No-Exam exceptions, or add replacement dates.": "مدیریت نوبت‌های آزمون، تعیین موارد بدون آزمون یا تاریخ‌های جایگزین.",
    "Manage reusable exam definitions and schedule dated occurrences with track-specific subject configurations.": "مدیریت تعاریف آزمون و زمان‌بندی تاریخ‌های برگزاری با تنظیم دروس به تفکیک رشته.",
    "Manage student accounts, credentials, and access permissions.": "مدیریت حساب دانش‌آموزان، اطلاعات ورود و دسترسی‌ها.",
    "Manage test resources organized by Subject &rarr; Book &rarr; Chapter with test counts.": "مدیریت منابع تست دسته‌بندی‌شده بر اساس درس، کتاب و فصل به همراه تعداد تست.",
    "Manage video courses organized by Subject &rarr; Teacher &rarr; Course &rarr; Chapter.": "مدیریت دوره‌های ویدیویی دسته‌بندی‌شده بر اساس درس، استاد، دوره و فصل.",
    "Manual duration required for custom tasks.": "برای تکالیف سفارشی، تعیین مدت زمان الزامی است.",
    "Mark Absent": "ثبت غیبت",
    "Mark Reviewed": "ثبت بررسی‌شده",
    "Meeting Link / URL": "لینک / آدرس اینترنتی جلسه",
    "Meeting URL:": "لینک ورود به جلسه:",
    "Meetings & Availability": "جلسات و زمان‌های در دسترس",
    "Message a Student": "ارسال پیام به دانش‌آموز",
    "Missing": "غایب / ثبت‌نشده",
    "Missing / Overdue": "غایب / دارای تاخیر",
    "Missing Submissions": "پاسخنامه‌های ثبت‌نشده",
    "Mode": "نحوه برگزاری",
    "Modify name or archive/deactivate this reusable exam.": "ویرایش نام یا آرشیو/غیرفعال‌سازی این آزمون.",
    "Modify subject details.": "ویرایش مشخصات درس.",
    "Monthly & daily schedule": "برنامه ماهانه و روزانه",
    "Must be a grade supported by the selected subject.": "باید یکی از پایه‌های تحصیلی پشتیبانی‌شده توسط درس باشد.",
    "Navigation Hub": "مرکز ناوبری",
    "New Date": "تاریخ جدید",
    "New Time": "ساعت جدید",
    "New Value": "مقدار جدید",
    "Next Upcoming": "جلسه بعدی پیش‌رو",
    "No Grade": "بدون پایه",
    "No active subjects configured for this student.": "دروس فعالی برای این دانش‌آموز تنظیم نشده است.",
    "No archived plans for this student yet.": "هنوز برنامه آرشیوشده‌ای برای این دانش‌آموز وجود ندارد.",
    "No audit log entries recorded for this exam series yet.": "هنوز هیچ رکوردی در تاریخچه حسابرسی این سری آزمون ثبت نشده است.",
    "No audit records logged for this assignment yet.": "هنوز گزارش حسابرسی برای این تکلیف ثبت نشده است.",
})

with open(fa_path, "w", encoding="utf-8") as f:
    json.dump(fa, f, ensure_ascii=False, indent=2)
print("Part 4 complete.")
