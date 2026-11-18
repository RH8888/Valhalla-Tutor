import json
from pathlib import Path

fa_path = Path("app/locales/fa.json")
with open(fa_path, "r", encoding="utf-8") as f:
    fa = json.load(f)

# Part 9: Scheduling, Messaging, and Select Prompts
fa.update({
    "Scheduled Exam Sessions": "نوبت‌های آزمون برنامه‌ریزی‌شده",
    "Scheduled sessions, history, and attendance records for .": "جلسات برنامه‌ریزی‌شده، سوابق و حضور و غیاب برای این دانش‌آموز.",
    "Scheduled:": "برنامه‌ریزی‌شده برای:",
    "Score %": "درصد نمره %",
    "Score per curriculum subject.": "درصد به تفکیک دروس برنامه آموزشی.",
    "Score records & reports": "کارنامه‌ها و سوابق نمرات",
    "Select Curriculum Subjects": "انتخاب دروس برنامه آموزشی",
    "Select Grade...": "انتخاب پایه...",
    "Select Student...": "انتخاب دانش‌آموز...",
    "Select Subject...": "انتخاب درس...",
    "Select Track (Optional)...": "انتخاب رشته (اختیاری)...",
    "Select Track...": "انتخاب رشته...",
    "Select a student from the inbox on the left, or click \"+ New Chat\" to start messaging any student.": "یک دانش‌آموز را از فهرست سمت راست انتخاب کنید، یا دکمه «+ گفتگوی جدید» را بزنید.",
    "Select each track participating in this exam, and choose which subjects will be included for that track.": "رشته‌های شرکت‌کننده در این آزمون و دروس مربوط به هر رشته را تعیین کنید.",
    "Select one or multiple academic grades.": "یک یا چند پایه تحصیلی را انتخاب کنید.",
    "Select the custom subjects for this student. This customization will isolate this student from future track changes.": "دروس اختصاصی این دانش‌آموز را مشخص کنید. این تنظیمات مستقل از تغییرات کلی رشته خواهد بود.",
    "Semi-Automatic Weekly Scheduler": "برنامه‌ریز هفتگی نیمه‌خودکار",
    "Send a message below to start the conversation.": "برای شروع گفتگو، پیام خود را در کادر زیر بنویسید.",
    "Send a message to start communicating with your tutor.": "برای ارتباط با استاد راهنما، پیام خود را ارسال نمایید.",
    "Send in-app notice": "ارسال اعلان درون‌برنامه‌ای",
    "Sent": "ارسال شد",
    "Series": "سری آزمون",
    "Session Title": "عنوان جلسه / نوبت",
    "Session Title / Notes (Optional)": "عنوان جلسه / یادداشت‌ها (اختیاری)",
    "Set": "تنظیم",
    "Settings": "تنظیمات",
    "Skip (No Exam)": "رد کردن (بدون آزمون)",
    "Some assigned students have transitioned grade or track and are no longer eligible for their assigned series.": "برخی از دانش‌آموزان تغییر پایه یا رشته داده‌اند و دیگر شرایط شرکت در این آزمون را ندارند.",
    "Sorted by completion date (newest first)": "مرتب‌شده بر اساس تاریخ تکمیل (جدیدترین در ابتدا)",
    "Start Date (Day 1)": "تاریخ شروع (روز اول)",
    "Start Exam &rarr;": "شروع آزمون &larr;",
    "Start Question # *": "شماره سوال شروع *",
    "Start Test #": "شماره تست شروع",
    "Start Time ()": "ساعت شروع",
    "Start Video #": "شماره ویدیوی شروع",
    "Start a conversation with a student using the button above.": "با استفاده از دکمه بالا، یک گفتگوی جدید با دانش‌آموز آغاز نمایید.",
    "Started": "شروع شد",
    "Strict tutor-only audit log": "گزارش حسابرسی محرمانه استاد",
    "Student *": "دانش‌آموز *",
})

with open(fa_path, "w", encoding="utf-8") as f:
    json.dump(fa, f, ensure_ascii=False, indent=2)
print("Part 9 complete.")
