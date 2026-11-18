import json
from pathlib import Path

fa_path = Path("app/locales/fa.json")
with open(fa_path, "r", encoding="utf-8") as f:
    fa = json.load(f)

# Batch 4: Comprehensive coverage of remaining user-facing phrases
fa.update({
    "Archived &amp; Previous Plans": "برنامه‌های آرشیوشده و پیشین",
    "Archived &bull; Read-Only": "آرشیو شده &bull; فقط‌خواندنی",
    "Archived (Read-Only)": "آرشیو شده (فقط‌خواندنی)",
    "Archived Plan": "برنامه آرشیو شده",
    "Assign Students to Exam Series": "تخصیص دانش‌آموزان به سری آزمون",
    "Assign a new password. Existing active sessions will be revoked.": "تنظیم رمز عبور جدید. نشست‌های فعال فعلی باطل خواهند شد.",
    "Assign an academic track or customize individual curriculum subjects.": "انتخاب رشته تحصیلی یا شخصی‌سازی دروس دانش‌آموز.",
    "Assigned": "تخصیص‌یافته",
    "Assigned Series:": "سری‌های آزمون اختصاص‌یافته:",
    "Assignment Audit Trail": "ردپای تغییرات و حسابرسی تکالیف",
    "Assigns chosen subject to questions within range.": "درس انتخابی را به سوالات این بازه اختصاص می‌دهد.",
    "At meeting time": "در زمان شروع جلسه",
    "Attach student's official report card (PDF, PNG, JPG, WEBP - Max 15MB).": "پیوست کارنامه رسمی دانش‌آموز (PDF، تصویر - حداکثر ۱۵ مگابایت).",
    "Attached:": "پیوست شده:",
    "Attempts": "تعداد دفعات آزمون",
    "Audit History & Activity Log": "تاریخچه تغییرات و گزارش فعالیت‌ها",
    "Audit log preserved when resetting accidental completions.": "گزارش حسابرسی در هنگام بازنشانی وضعیت حفظ می‌شود.",
    "Average Rank": "میانگین رتبه",
    "Avg": "میانگین",
    "Awaiting": "در انتظار",
    "Awaiting Results": "در انتظار ثبت نتایج",
    "Book": "کتاب",
    "Book / Tests": "کتاب تست / تمرین",
    "Book Chapters": "فصل‌های کتاب",
    "Book Title *": "عنوان کتاب *",
    "Booklet Locked:": "دفترچه قفل است:",
    "Booklet Title *": "عنوان دفترچه *",
    "Booklet tests & instant grading": "دفترچه آزمون با تصحیح و نمره‌دهی آنی",
    "Booklets & mock assessments": "دفترچه‌ها و آزمون‌های شبیه‌ساز",
    "Books": "کتاب‌های درسی",
    "Books &rarr;": "کتاب‌ها &larr;",
    "Bulk Results & Submission Progress Overview": "نمای کلی پیشرفت ثبت نمرات و کارنامه‌ها",
    "Calendar &rarr;": "تقویم &larr;",
    "Cancel Meeting": "لغو جلسه",
    "Change Log Records": "سوابق تغییرات ثبت‌شده",
    "Chapter": "فصل",
    "Chapter Name *": "نام فصل *",
    "Chapter Title *": "عنوان فصل *",
    "Check one or more academic grades that this subject applies to.": "پایه‌های تحصیلی که این درس به آن‌ها تعلق دارد را انتخاب کنید.",
    "Choose a student...": "انتخاب یک دانش‌آموز...",
    "Clear Filter": "پاک کردن فیلتر",
    "Click the button below to schedule an appointment with a student.": "برای تنظیم وقت جلسه با دانش‌آموز، دکمه زیر را کلیک کنید.",
    "Combined subject reporting configured for this exam track.": "گزارش‌گیری ترکیبی دروس برای این رشته آزمونی تنظیم شده است.",
})

with open(fa_path, "w", encoding="utf-8") as f:
    json.dump(fa, f, ensure_ascii=False, indent=2)
print("Batch 4 added.")
