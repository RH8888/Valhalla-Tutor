import json
from pathlib import Path

fa_path = Path("app/locales/fa.json")
with open(fa_path, "r", encoding="utf-8") as f:
    fa = json.load(f)

# Part 7: Chat, Practice Tests, Audit Logs, and Descriptions
fa.update({
    "Practice Exams (آزمون‌های تمرینی)": "آزمون‌های تمرینی",
    "Practice Tests &rarr;": "آزمون‌های تمرینی &larr;",
    "Practice exams assigned to you by your tutor will appear here.": "آزمون‌های تمرینی اختصاص‌یافته توسط استاد شما در اینجا نمایش داده خواهند شد.",
    "Practice exams assigned to your grade and track. Download PDF booklets, submit answers, and receive instant graded results.": "آزمون‌های تمرینی پایه و رشته شما. دانلود دفترچه PDF، ارسال پاسخ‌ها و دریافت کارنامه آنی.",
    "Predefined Default": "پیش‌فرض سامانه",
    "Press Enter to send, Shift+Enter for new line. Max 5,000 characters.": "برای ارسال Enter و برای خط جدید Shift+Enter را بزنید. حداکثر ۵۰۰۰ کاراکتر.",
    "Preview your schedule and prepare in advance": "برنامه روزهای آینده خود را ببینید و از قبل آماده شوید",
    "Previous Meetings ()": "جلسات گذشته",
    "Previous Value": "مقدار قبلی",
    "Private Chat": "گفتگوی خصوصی",
    "Private Tutor Notes": "یادداشت‌های محرمانه استاد",
    "Profile &rarr;": "پروفایل &larr;",
    "Q #": "سوال #",
    "Quick access to all areas of your academic platform.": "دسترسی سریع به تمامی بخش‌های سامانه آموزشی شما.",
    "Quick:": "سریع:",
    "Rank:": "رتبه:",
    "Read": "خوانده‌شده",
    "Read-Only Mode:": "حالت فقط‌خواندنی:",
    "Read-only historical review": "مرور سوابق گذشته (فقط‌خواندنی)",
    "Reason / Details": "علت / توضیحات",
    "Reason for Rescheduling": "علت جابجایی زمان جلسه",
    "Reason:": "علت:",
    "Recommended duration": "مدت زمان پیشنهادی",
    "Recommended effort": "زمان مطالعه پیشنهادی",
    "Record Historical External Exam": "ثبت کارنامه آزمون آزمایشی گذشته",
    "Record past institute results taken by students before joining.": "ثبت نمرات آزمون‌های قبلی دانش‌آموزان در موسسات آموزشی.",
    "Recorded Audit Entries ()": "تعداد تغییرات ثبت‌شده",
    "Recorded completion timestamp:": "زمان ثبت انجام تکلیف:",
    "Recorded:": "ثبت‌شده در:",
    "Recurring Schedule Configuration (Optional)": "تنظیمات زمان‌بندی تکرارشونده (اختیاری)",
    "Recurring availability slots": "بازه‌های زمانی تکرارشونده استاد",
    "Reference books & resources": "کتاب‌های کمک‌آموزشی و منابع تستی",
    "Register a teacher's course under a subject.": "ثبت دوره ویدیویی یک استاد ذیل یک درس مشخص.",
    "Register a test book under an academic subject.": "ثبت کتاب تست یا منبع آموزشی ذیل یک درس مشخص.",
    "Register test books and log chapter test counts for study planning.": "ثبت کتاب‌های تستی و تعیین تعداد تست‌های هر فصل برای برنامه‌ریزی مطالعاتی.",
    "Registered exam series": "سری‌های آزمون آزمایشی ثبت‌شده",
    "Remaining Today": "باقی‌مانده‌های امروز",
    "Reminder:": "یادآور:",
    "Remove": "حذف",
})

with open(fa_path, "w", encoding="utf-8") as f:
    json.dump(fa, f, ensure_ascii=False, indent=2)
print("Part 7 complete.")
