import json
from pathlib import Path

fa_path = Path("app/locales/fa.json")
with open(fa_path, "r", encoding="utf-8") as f:
    fa = json.load(f)

# Part 8: Review, Save buttons, Reporting, Schedule
fa.update({
    "Reopen": "بازگشایی مجدد",
    "Report Card (کارنامه)": "کارنامه آزمون",
    "Report Card / Result Sheet (کارنامه)": "کارنامه رسمی آزمون",
    "Reported study duration: minutes": "زمان مطالعه گزارش‌شده: دقیقه",
    "Reported study time: m": "زمان مطالعه ثبت‌شده: دقیقه",
    "Reported: m": "گزارش‌شده: دقیقه",
    "Reported: min": "گزارش‌شده: دقیقه",
    "Reporting Group": "گروه گزارش‌گیری",
    "Reporting Groups Breakdown": "تفکیک گروه‌های کارنامه",
    "Reporting Groups:": "گروه‌های کارنامه:",
    "Reset Password": "تغییر رمز عبور",
    "Restore": "بازگردانی",
    "Resume Exam &rarr;": "ادامه آزمون &larr;",
    "Retake Permissions": "مجوزهای شرکت مجدد در آزمون",
    "Reusable Exam Definitions": "تعاریف آزمون‌های چندبارمصرف",
    "Reusable curriculum subjects across academic tracks, courses, and books.": "دروس آموزشی قابل استفاده در رشته‌ها، دوره‌ها و کتاب‌ها.",
    "Review": "بازبینی و بررسی",
    "Review Alerts &rarr;": "بررسی هشدارها &larr;",
    "Review Plan &rarr;": "بازبینی برنامه &larr;",
    "Review Proposed Weekly Schedule": "بازبینی پیشنهاد برنامه هفتگی",
    "Review Results &rarr;": "مشاهده نتایج &larr;",
    "Review all your completed study tasks and recorded timestamps.": "مرور تمامی تکالیف تکمیل‌شده و زمان‌های ثبت‌شده.",
    "Review all your previous and archived 14-day study plans.": "مرور تمامی برنامه‌های مطالعاتی گذشته و آرشیوشده ۱۴ روزه شما.",
    "Review your assigned track, enrolled subjects, and available learning resources.": "بررسی رشته تحصیلی، دروس ثبت‌نام‌شده و منابع یادگیری در دسترس شما.",
    "Reviewed": "بررسی شد",
    "Save Adjustment": "ذخیره تغییرات",
    "Save Assignments": "ذخیره تخصیص تکالیف",
    "Save Book Info": "ذخیره اطلاعات کتاب",
    "Save ChangesSchedule Meeting": "ذخیره تغییرات جلسه",
    "Save Course Info": "ذخیره اطلاعات دوره",
    "Save Historical Result": "ثبت کارنامه گذشته",
    "Save Question Keys &amp; Groups": "ذخیره کلید پاسخ‌ها و گروه‌بندی",
    "Save Reporting Structure": "ذخیره ساختار کارنامه",
    "Save Track Info": "ذخیره اطلاعات رشته",
    "Schedule & Meetings": "برنامه زمانی و جلسات",
    "Schedule ()": "برنامه زمانی",
    "Schedule Exam Session": "زمان‌بندی نوبت آزمون",
    "Schedule Hub": "مرکز برنامه زمانی و جلسات",
    "Schedule Modification Audit Trail": "ردپای تغییرات در زمان‌بندی جلسات",
})

with open(fa_path, "w", encoding="utf-8") as f:
    json.dump(fa, f, ensure_ascii=False, indent=2)
print("Part 8 complete.")
