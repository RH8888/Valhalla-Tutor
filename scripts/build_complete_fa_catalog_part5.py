import json
from pathlib import Path

fa_path = Path("app/locales/fa.json")
with open(fa_path, "r", encoding="utf-8") as f:
    fa = json.load(f)

# Part 5: Empty states, No ... messages, & status confirmations
fa.update({
    "No booklets uploaded yet.": "هنوز دفترچه‌ای برای این آزمون بارگذاری نشده است.",
    "No chapters added to this book yet. Use the form below to add chapters.": "هنوز فصلی به این کتاب افزوده نشده است. از فرم زیر جهت افزودن فصل استفاده کنید.",
    "No chapters added to this course yet. Use the form to add chapters.": "هنوز فصلی به این دوره اضافه نشده است. از فرم زیر جهت افزودن فصل استفاده کنید.",
    "No combined groups defined (subjects scored individually).": "گروه ترکیبی تعریف نشده است (نمرات دروس به صورت انفرادی محاسبه می‌شوند).",
    "No completed tasks yet.": "هنوز تکلیفی تکمیل نشده است.",
    "No conversation selected": "گفتگویی انتخاب نشده است",
    "No conversations": "هیچ گفتگویی وجود ندارد",
    "No eligible students found matching the configured grade/track combinations.": "دانش‌آموزی مطابق با شرایط پایه و رشته تعیین‌شده یافت نشد.",
    "No exam occurrences found matching the criteria.": "هیچ نوبت آزمونی مطابق با این معیارها یافت نشد.",
    "No exam results recorded for this student yet.": "هنوز نتیجه آزمونی برای این دانش‌آموز ثبت نشده است.",
    "No exam results recorded yet.": "هنوز نتیجه آزمونی ثبت نشده است.",
    "No further upcoming meetings.": "جلسه پیش‌روی دیگری وجود ندارد.",
    "No historical exam records found.": "هیچ سابقه آزمونی یافت نشد.",
    "No link provided": "لینکی وارد نشده است",
    "No meetings": "جلسه‌ای وجود ندارد",
    "No meetings scheduled for this day": "هیچ جلسه‌ای برای این روز تنظیم نشده است",
    "No meetings scheduled for today.": "هیچ جلسه‌ای برای امروز برنامه‌ریزی نشده است.",
    "No messages yet": "هنوز پیامی وجود ندارد",
    "No occurrences generated yet. Configure recurrence and click": "هنوز نوبتی ایجاد نشده است. بازه تکرار را تنظیم کرده و کلیک کنید",
    "No past exams found.": "هیچ آزمون گذشته‌ای یافت نشد.",
    "No practice exams created yet.": "هنوز آزمون تمرینی ایجاد نشده است.",
    "No practice exams currently available.": "در حال حاضر آزمون تمرینی فعالی وجود ندارد.",
    "No previous meetings recorded.": "جلسه گذشته‌ای ثبت نشده است.",
    "No reminder": "بدون یادآور",
    "No score submitted": "نمره‌ای ثبت نشده است",
    "No student attempts recorded for this practice exam yet.": "هنوز تلاشی از دانش‌آموزان برای این آزمون ثبت نشده است.",
    "No students found for this grade/track configuration.": "دانش‌آموزی برای این ترکیب پایه و رشته یافت نشد.",
    "No students have submitted results for this exam session yet.": "هنوز دانش‌آموزی کارنامه خود را برای این نوبت آزمون ثبت نکرده است.",
    "No study plans created for this student yet. Use the form above to start a 14-day plan.": "هنوز برنامه مطالعاتی برای این دانش‌آموز ساخته نشده است. از فرم بالا برای شروع یک برنامه ۱۴ روزه استفاده کنید.",
    "No subjects configured in this academic track yet.": "هنوز درسی برای این رشته تحصیلی تعریف نشده است.",
    "No subjects configured in this track yet.": "هنوز درسی در این رشته ثبت نشده است.",
    "No subjects defined yet.": "هنوز درسی تعریف نشده است.",
    "No subjects enrolled.": "درسی ثبت‌نام نشده است.",
    "No subjects exist yet. You can add subjects after creating the track.": "هنوز درسی وجود ندارد. پس از ساخت رشته می‌توانید دروس را اضافه کنید.",
    "No subjects in this track yet.": "هنوز درسی در این رشته قرار ندارد.",
    "No test books registered yet.": "هنوز کتاب تستی ثبت نشده است.",
    "No upcoming exams scheduled at this time.": "در حال حاضر آزمونی در پیش رو نیست.",
    "No upcoming meetings scheduled": "جلسه پیش‌رویی تنظیم نشده است",
    "No upcoming meetings scheduled.": "هیچ جلسه آینده‌ای برنامه‌ریزی نشده است.",
    "No video courses registered yet.": "هنوز دوره ویدیویی ثبت نشده است.",
    "None": "هیچ‌کدام",
    "None specified": "مشخص نشده",
})

with open(fa_path, "w", encoding="utf-8") as f:
    json.dump(fa, f, ensure_ascii=False, indent=2)
print("Part 5 complete.")
