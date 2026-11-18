import json
from pathlib import Path

fa_path = Path("app/locales/fa.json")
with open(fa_path, "r", encoding="utf-8") as f:
    fa = json.load(f)

# Part 6: Guidance, Occurrences, Analytics, & Form Details
fa.update({
    "Not assigned": "اختصاص داده نشده",
    "Not started yet": "هنوز شروع نشده",
    "Notes:": "نکات:",
    "Occurrence / Date": "نوبت برگزاری / تاریخ",
    "Occurrence Status": "وضعیت نوبت برگزاری",
    "Occurrences Matrix": "ماتریس نوبت‌های آزمون",
    "Off All Day -": "تمام روز تعطیل -",
    "On Track &mdash; Student is keeping up with their scheduled workload.": "طبق برنامه &mdash; دانش‌آموز مطابق با حجم تکالیف پیش‌بینی‌شده پیش می‌رود.",
    "Once the student submits results for scheduled exams, full performance trends and analytics will appear here.": "به محض اینکه دانش‌آموز نتایج آزمون‌های خود را ثبت کند، نمودارهای روند و تحلیل عملکرد در اینجا نمایش داده خواهند شد.",
    "Once you mark assignments complete from your dashboard or study plan, they will appear here.": "به محض اینکه تکالیف را از داشبورد یا برنامه مطالعاتی تیک بزنید، در این بخش نمایش داده می‌شوند.",
    "Online meeting": "جلسه آنلاین",
    "Open Calendar to schedule appointments &rarr;": "رفتن به تقویم برای تنظیم وقت جلسات &larr;",
    "Open Chat": "باز کردن گفتگو",
    "Open Plan &rarr;": "مشاهده برنامه &larr;",
    "Open Planner &rarr;": "ورود به برنامه‌ریز &larr;",
    "Optional. Attach official institute report card (PDF, PNG, JPG, WEBP - Max 15MB).": "اختیاری. بارگذاری تصویر یا پی‌دی‌اف کارنامه رسمی موسسه (حداکثر ۱۵ مگابایت).",
    "Order": "ترتیب",
    "Organize tracks, subjects, video course chapters, and textbook test counts.": "سازماندهی رشته‌ها، دروس، فصول دوره‌های ویدیویی و تعداد تست‌های کتاب‌ها.",
    "Overall Percentage": "درصد کل",
    "Overall Rank (رتبه کل)": "رتبه کل",
    "Overall Trend": "روند کلی",
    "PDF Booklets (دفترچه‌های سوال)": "دفترچه‌های سوال (PDF)",
    "PDF File *": "فایل PDF *",
    "Participating Tracks": "رشته‌های شرکت‌کننده",
    "Past Plans": "برنامه‌های گذشته",
    "Past external institute exams (قلم‌چی، سنجش، گزینه دو، ماز) recorded for students.": "سوابق کارنامه آزمون‌های موسسات (قلم‌چی، سنجش، گزینه دو، ماز) ثبت‌شده برای دانش‌آموزان.",
    "Past external institute exams (قلم‌چی، گزینه دو، سنجش، ماز) recorded for your profile.": "سوابق کارنامه آزمون‌های آزمایشی گذشته برای شما.",
    "Past scores & report cards": "نمرات و کارنامه‌های گذشته",
    "Past study plan iterations": "برنامه‌های مطالعاتی گذشته",
    "Paste numbers (1–4) or letters (A–D). Applies sequentially starting at Q#1.": "اعداد (۱ تا ۴) یا حروف (الف تا د) را بچسبانید. از سوال ۱ اعمال خواهد شد.",
    "Peak": "اوج عملکرد",
    "Pending Review": "در انتظار بررسی",
    "Percentage %": "درصد %",
    "Performance Trends &rarr;": "روند عملکرد &larr;",
    "Plan Completion": "درصد تکمیل برنامه",
    "Plan Title (Optional)": "عنوان برنامه (اختیاری)",
    "Plan Total Study Time": "مجموع زمان مطالعه برنامه",
    "Please contact your tutor to assign an academic track to your account.": "لطفاً با استاد راهنمای خود برای تعیین رشته تحصیلی تماس بگیرید.",
    "Please upload at least one PDF booklet first to define question numbers.": "لطفاً ابتدا حداقل یک دفترچه سوال PDF بارگذاری نمایید.",
    "Practice Exams (آزمون‌های اختصاصی)": "آزمون‌های اختصاصی و تمرینی",
})

with open(fa_path, "w", encoding="utf-8") as f:
    json.dump(fa, f, ensure_ascii=False, indent=2)
print("Part 6 complete.")
