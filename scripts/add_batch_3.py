import json
from pathlib import Path

fa_path = Path("app/locales/fa.json")
with open(fa_path, "r", encoding="utf-8") as f:
    fa = json.load(f)

# Batch 3: Practice exams, runner, analytics, submission matrix, books, courses
fa.update({
    "Practice Exam Runner": "سامانه برگزاری آزمون تمرینی",
    "Time Remaining": "زمان باقی‌مانده",
    "Flag": "نشان‌گذاری",
    "Flagged": "نشان‌شده",
    "Previous": "قبلی",
    "Next": "بعدی",
    "Question Navigation": "ناوبری سوالات",
    "Answer Key": "کلید پاسخ‌ها",
    "Answer Sheet": "پاسخ‌برگ",
    "Student Answers": "پاسخ‌های دانش‌آموز",
    "Booklet Summary": "خلاصه دفترچه",
    "Score & Percentage": "نمره و درصد",
    "Total Questions": "تعداد کل سوالات",
    "Attempt Date": "تاریخ آزمون",
    "Completed At": "زمان تکمیل",
    "Raw Score": "نمره خام",
    "Final Percentage": "درصد نهایی",
    "Correct Answers": "پاسخ‌های درست",
    "Incorrect Answers": "پاسخ‌های نادرست",
    "Unanswered Questions": "سوالات بدون پاسخ",
    "Booklet is not unlocked yet.": "این دفترچه هنوز باز نشده است.",
    "Practice Exam Details": "جزئیات آزمون تمرینی",
    "Configure Questions & Answer Key": "تنظیم سوالات و کلید پاسخ‌ها",
    "Assign to Students": "تخصیص به دانش‌آموزان",
    "Upload Booklet PDF": "بارگذاری فایل PDF دفترچه",
    "Booklet Title": "عنوان دفترچه",
    "Duration (Minutes)": "مدت زمان (دقیقه)",
    "Order Index": "ترتیب نمایش",
    "Number of Questions": "تعداد سوالات",
    "Negative Score Weight": "ضریب نمره منفی",
    "Correct Score Weight": "ضریب نمره مثبت",
    "Reporting Groups": "گروه‌های کارنامه",
    "Add Reporting Group": "افزودن گروه کارنامه",
    "Group Title": "عنوان گروه",
    "Subject": "درس",
    "Question Range": "بازه سوالات",
    "Start Question": "از سوال",
    "End Question": "تا سوال",
    "Course Title": "عنوان دوره",
    "Instructor": "مدرس",
    "Course Chapters": "فصل‌های دوره",
    "Add Chapter": "افزودن فصل",
    "Video URL": "آدرس اینترنتی ویدیو",
    "Book Title": "عنوان کتاب",
    "Publisher": "ناشر",
    "Author / Compiler": "مولف / گردآورنده",
    "Publication Year": "سال انتشار",
    "Chapters & Table of Contents": "فصل‌ها و فهرست کتاب",
    "Chapter Title": "عنوان فصل",
    "Page Count": "تعداد صفحات",
    "Exercises Count": "تعداد تمرین‌ها / تست‌ها",
    "No books found": "هیچ کتابی ثبت نشده است",
    "No courses found": "هیچ دوره ویدیویی ثبت نشده است",
    "No exams registered": "هیچ آزمونی ثبت نشده است",
    "No practice attempts yet": "هنوز تلاشی برای این آزمون ثبت نشده است",
})

with open(fa_path, "w", encoding="utf-8") as f:
    json.dump(fa, f, ensure_ascii=False, indent=2)
print("Batch 3 added.")
