import json
from pathlib import Path

fa_path = Path("app/locales/fa.json")
with open(fa_path, "r", encoding="utf-8") as f:
    fa = json.load(f)

# Batch 1: Headings, Descriptions, and Core Guidance
fa.update({
    "1. Eligible Academic Groups & Reporting Structures": "۱. گروه‌های تحصیلی مجاز و ساختار گزارش‌گیری",
    "2. Scheduled Occurrences & Exceptions": "۲. نوبت‌های برنامه‌ریزی‌شده و موارد استثنا",
    "Academic Curriculum & Subjects": "برنامه درسی و رشته‌های تحصیلی",
    "Academic Structure & Learning Content": "ساختار آموزشی و محتوای یادگیری",
    "Active Published Plan": "برنامه مطالعاتی فعال منتشرشده",
    "Active Subjects for this Student": "دروس فعال این دانش‌آموز",
    "Assigned Academic Track": "رشته تحصیلی اختصاص‌یافته",
    "Assigned Track": "رشته اختصاص‌یافته",
    "Behind Planned Workload": "عقب‌تر از برنامه پیش‌بینی‌شده",
    "Current Effective Subjects": "دروس موثر جاری",
    "Daily Schedule Progress (14 Days)": "پیشرفت برنامه روزانه (۱۴ روز)",
    "Edit Task": "ویرایش تکلیف",
    "Enrolled Subjects": "دروس ثبت‌نام‌شده",
    "External Exam Event": "رویداد آزمون آزمایشی",
    "Group Comparison": "مقایسه گروهی دانش‌آموزان",
    "Individually Customized Curriculum": "برنامه درسی اختصاصی‌سازی‌شده",
    "Individually Customized": "شخصی‌سازی‌شده برای دانش‌آموز",
    "Default Track Subjects": "دروس استاندارد رشته",
    "No Track Assigned": "رشته‌ای اختصاص داده نشده است",
    "Meetings & Appointments": "جلسات و قرارها",
    "Move Task": "انتقال تکلیف",
    "My Academic Curriculum": "برنامه درسی من",
    "My Curriculum": "برنامه درسی من",
    "No Active Published Plan": "هیچ برنامه مطالعاتی فعالی منتشر نشده است",
    "No Active Study Plan Available": "برنامه مطالعاتی فعالی در دسترس نیست",
    "No Active Study Plan Yet": "هنوز برنامه فعالی وجود ندارد",
    "No Exam": "بدون آزمون",
    "No Exam (Skipped)": "بدون آزمون (برگزار نمی‌شود)",
    "No Study Plans Found": "هیچ برنامه مطالعاتی یافت نشد",
    "No Tasks Scheduled for Today!": "هیچ تکلیفی برای امروز ثبت نشده است!",
    "No academic tracks found.": "هیچ رشته تحصیلی یافت نشد.",
    "No active students enrolled.": "هیچ دانش‌آموز فعالی ثبت‌نام نشده است.",
    "No active subjects assigned yet.": "هنوز درسی به این دانش‌آموز اختصاص نیافته است.",
    "No completed tasks logged for this student yet.": "هنوز تکلیفی برای این دانش‌آموز ثبت نشده است.",
    "No upcoming days remaining in this 14-day study sprint.": "هیچ روز باقی‌مانده‌ای در این دوره ۱۴ روزه وجود ندارد.",
    "No tasks": "تکلیفی وجود ندارد",
    "On Track": "مطابق با برنامه",
    "On Schedule": "طبق زمان‌بندی",
    "Behind": "عقب‌تر از برنامه",
    "Pace Status": "وضعیت پیشرفت",
    "Pending Tasks": "تکالیف در انتظار انجام",
    "Completed Tasks": "تکالیف تکمیل‌شده",
    "Recent Completed Tasks": "تکالیف اخیراً تکمیل‌شده",
    "Scheduled workload adherence": "پایبندی به زمان‌بندی تکالیف",
    "Step 1: Your Day-by-Day Availability Windows": "مرحله ۱: بازه‌های زمانی در دسترس شما به تفکیک روز",
    "Step 2: Select Students & Meeting Days": "مرحله ۲: انتخاب دانش‌آموزان و روزهای جلسه",
    "Student Profile": "پروفایل دانش‌آموز",
    "Student Results & Submissions": "نتایج و پاسخنامه‌های دانش‌آموزان",
    "Study Plan & Progress Monitoring": "برنامه مطالعاتی و نظارت بر پیشرفت",
    "Subject Completion Breakdown": "تفکیک تکمیل تکالیف به تفکیک درس",
    "Today's Study Checklist": "چک‌لیست مطالعاتی امروز",
    "Today's Study Load": "حجم مطالعه امروز",
    "Upcoming Days & Workload": "روزهای پیش‌رو و حجم مطالعه",
})

with open(fa_path, "w", encoding="utf-8") as f:
    json.dump(fa, f, ensure_ascii=False, indent=2)
print("Batch 1 added.")
