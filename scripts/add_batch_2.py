import json
from pathlib import Path

fa_path = Path("app/locales/fa.json")
with open(fa_path, "r", encoding="utf-8") as f:
    fa = json.load(f)

# Batch 2: Form labels, placeholders, table column labels, modals
fa.update({
    "Full Name": "نام و نام خانوادگی",
    "Username": "نام کاربری",
    "Initial Password": "رمز عبور اولیه",
    "New Password": "رمز عبور جدید",
    "Update Password": "تغییر رمز عبور",
    "Email Address": "آدرس ایمیل",
    "Email": "ایمیل",
    "Academic Grade": "پایه تحصیلی",
    "Academic Track": "رشته تحصیلی",
    "Timezone": "منطقه زمانی",
    "Account Status": "وضعیت حساب کاربری",
    "Target Day": "روز مقصد",
    "Target Subject": "درس مقصد",
    "Recommended Duration (Minutes)": "مدت زمان پیشنهادی (دقیقه)",
    "Recommended Duration": "مدت زمان پیشنهادی",
    "Description / Notes": "توضیحات / نکات",
    "Permanently remove this assignment:": "حذف دائمی این تکلیف از برنامه:",
    "Reset to Track": "بازنشانی به تنظیمات پیش‌فرض رشته",
    "Save Track": "ذخیره رشته تحصیلی",
    "Save Customized Subjects": "ذخیره دروس شخصی‌سازی‌شده",
    "⚙️ Customize Individual Student Subjects": "⚙️ شخصی‌سازی دروس این دانش‌آموز",
    "Select Meeting Day(s) for this week:": "انتخاب روزهای جلسه در این هفته:",
    "Duration & Mode:": "مدت زمان و نوع جلسه:",
    "Tutor Windows:": "بازه‌های زمانی استاد:",
    "Proposed Sessions": "جلسات پیشنهادی",
    "Edit any time before approving": "امکان ویرایش قبل از تایید نهایی وجود دارد",
    "✏️ Change Time / Details &darr;": "✏️ تغییر ساعت / جزئیات &darr;",
    "Notice:": "توجه:",
    "Approving will schedule these appointments on the calendar, setup in-app reminders, and privately notify each student in their chat conversation.": "تایید نهایی این جلسات را در تقویم ثبت نموده، یادآورها را فعال کرده و پیام خصوصی برای هر دانش‌آموز ارسال خواهد کرد.",
    "✓ Approve & Schedule Week": "✓ تایید و ثبت نهایی برنامه هفته",
    "This schedule proposal has been approved. All sessions are live in the calendar and students have been notified.": "این پیشنهاد برنامه تایید شده است. تمام جلسات در تقویم فعال بوده و دانش‌آموزان مطلع شده‌اند.",
    "The algorithm will check availability, prevent conflicts, and use learned hours.": "الگوریتم زمان‌بندی تداخل‌ها را بررسی کرده و ساعت‌های ترجیحی را در نظر می‌گیرد.",
    "Weekly Scheduling Protocol (Asia/Tehran):": "دستورالعمل زمان‌بندی هفتگی (به وقت تهران):",
    "Weekly schedules are prepared on Friday for the following week. Any meetings planned for Saturday should be finalized by Thursday. Recommendations are learned from completed sessions.": "برنامه‌های هفتگی در روز جمعه برای هفته آینده آماده می‌شوند. هر جلسه‌ای برای شنبه باید تا پنج‌شنبه نهایی شود.",
    "You have an active draft proposal": "شما یک پیش‌نویس فعال پیشنهاد برنامه هفتگی دارید",
    "Scheduling Conflict / Limitation:": "تداخل یا محدودیت زمان‌بندی:",
    "Specify custom hours for each day, or select \"Day Off / No Window\" if you do not want sessions on that day.": "ساعت‌های دلخواه برای هر روز را مشخص کنید یا برای روزهای بدون جلسه گزینه «روز تعطیل» را انتخاب نمایید.",
    "Presets:": "پیش‌فرض‌ها:",
    "From": "از ساعت",
    "Until": "تا ساعت",
    "🏖️ Day Off (No Sessions)": "🏖️ روز تعطیل (بدون جلسه)",
    "Select all": "انتخاب همه",
    "Bulk Action:": "عملیات گروهی:",
    "Reason (optional)": "علت (اختیاری)",
    "Skip Reason / Notes": "علت رد شدن / یادداشت",
    "Results": "نتایج",
    "Never silently modifies submitted results": "نمرات ثبت‌شده هرگز تغییر داده نخواهند شد",
    "Student Results": "کارنامه دانش‌آموزان",
    "Student": "دانش‌آموز",
    "Overall Rank": "رتبه کل",
    "Correct / Incorrect": "درست / نادرست",
    "Average %": "میانگین %",
    "Status / Review": "وضعیت / بازبینی",
    "Report Card": "کارنامه",
    "Monitoring": "نظارت",
    "Group Comparison": "مقایسه گروهی",
    "Restore Occurrence": "بازگردانی برگزاری آزمون",
    "Averages across students:": "میانگین بین دانش‌آموزان:",
    "Participating Tracks & Configured Subjects": "رشته‌های شرکت‌کننده و دروس تعریف‌شده",
})

with open(fa_path, "w", encoding="utf-8") as f:
    json.dump(fa, f, ensure_ascii=False, indent=2)
print("Batch 2 added.")
