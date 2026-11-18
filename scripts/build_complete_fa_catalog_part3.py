import json
from pathlib import Path

fa_path = Path("app/locales/fa.json")
with open(fa_path, "r", encoding="utf-8") as f:
    fa = json.load(f)

# Part 3: Management, Configuration, & In-App UI
fa.update({
    "Archived Study Plan": "برنامه مطالعاتی آرشیوشده",
    "My 14-Day Study Plan": "برنامه مطالعاتی ۱۴ روزه من",
    "Booklet Questions": "سوالات دفترچه",
    "By default eligible students in Grade &bull; can take this exam. You can also assign it directly.": "دانش‌آموزان واجد شرایط این پایه می‌توانند در آزمون شرکت کنند. امکان تخصیص مستقیم نیز وجود دارد.",
    "Combine multiple subjects (e.g. Geometry + Calculus + Stats &rarr; \"Mathematics\") into a single combined percentage report, or leave individual.": "می‌توانید چند درس (مانند هندسه + حسابان + آمار) را در یک درصد ترکیبی «ریاضیات» تجمیع کنید یا به صورت جداگانه نگه دارید.",
    "Compare &rarr;": "مقایسه &larr;",
    "Comparing students on occurrence:": "مقایسه دانش‌آموزان در نوبت آزمون:",
    "Completed Assignments ()": "تکالیف تکمیل‌شده",
    "Completed Score": "نمره کسب‌شده",
    "Completed on:": "تکمیل شده در تاریخ:",
    "Completed tasks cannot be deleted. Reset completion status first if needed.": "تکالیف تکمیل‌شده قابل حذف نیستند. در صورت نیاز ابتدا وضعیت تکمیل را بازنشانی کنید.",
    "Completed tasks cannot be moved or have their subject changed. Reset completion status first if needed.": "تکالیف تکمیل‌شده قابل انتقال یا تغییر درس نیستند. ابتدا وضعیت تکمیل را ریست کنید.",
    "Completion timestamp": "زمان دقیق تکمیل",
    "Configure Grade & Track Report Structure": "تنظیم ساختار کارنامه پایه و رشته",
    "Configure assignment details and duration": "تنظیم مشخصات و مدت زمان تکلیف",
    "Configure correct choices (1-4), subject assignment, and optional combined reporting group.": "تنظیم گزینه‌های صحیح (۱ تا ۴)، تخصیص دروس و گروه‌های کارنامه.",
    "Configure date and select which subjects are included for each participating academic track.": "تعیین تاریخ و انتخاب دروس آزمون برای هر رشته تحصیلی.",
    "Configure default recurrence to generate exam dates until the end of the academic year.": "تنظیم بازه تکرار برای تولید خودکار تاریخ‌های آزمون تا پایان سال تحصیلی.",
    "Configure practice exam booklets, external exam schedules, and past results.": "تنظیم دفترچه‌های آزمون تمرینی، زمان‌بندی آزمون‌های آزمایشی و کارنامه‌های گذشته.",
    "Configure which subjects and reporting groups appear when students of this grade/track submit their results.": "تعیین دروسی که در هنگام ثبت کارنامه دانش‌آموزان این پایه/رشته نمایش داده می‌شوند.",
    "Configured Reporting Groups": "گروه‌های کارنامه تعریف‌شده",
    "Configured grade and track combinations with their reporting subject groupings.": "ترکیب‌های پایه و رشته به همراه گروه‌بندی دروس کارنامه.",
    "Confirm Assignments": "تایید تخصیص تکالیف",
    "Confirm Reschedule": "تایید جابجایی زمان",
    "Continue to Next Section &rarr;": "ادامه به بخش بعدی &larr;",
    "Corrected": "تصحیح‌شده",
    "Course / Teacher": "دوره / استاد",
    "Course Chapters ()": "فصل‌های دوره",
    "Course Name": "نام دوره",
    "Course Name *": "نام دوره *",
    "Course subject directory": "فهرست دروس آموزشی",
    "Create & Schedule Exam": "ایجاد و زمان‌بندی آزمون",
    "Create &amp; Proceed": "ایجاد و ادامه",
    "Create Academic Track": "ایجاد رشته تحصیلی",
    "Create Book": "ثبت کتاب جدید",
    "Create External Exam Series": "ایجاد سری آزمون‌های آزمایشی",
    "Create New 14-Day Study Plan": "ایجاد برنامه مطالعاتی جدید ۱۴ روزه",
    "Create Practice Exam": "ایجاد آزمون تمرینی جدید",
    "Create Test Book": "افزودن کتاب تست",
    "Create Video Course": "افزودن دوره ویدیویی",
    "Create a track or use the CLI to seed the default 'ریاضی' and 'تجربی' tracks.": "یک رشته جدید بسازید یا از رشته‌های پیش‌فرض 'ریاضی' و 'تجربی' استفاده کنید.",
    "Create courses for teachers and log available chapter video counts.": "تعریف دوره‌ها به تفکیک اساتید و ثبت تعداد جلسات هر فصل.",
    "Immutable, system-recorded audit trail of all management operations, status changes, and tutor corrections for": "ردپای تغییرات ثبت‌شده در سیستم برای کلیه عملیات مدیریتی و اصلاحات استاد:",
    "Improving Subjects": "دروس رو به رشد و پیشرفت",
    "In Progress": "در حال انجام",
    "In-App Reminder": "یادآور درون‌برنامه‌ای",
    "Inactive": "غیرفعال",
    "Included Subjects for :": "دروس شامل‌شده برای:",
    "Incompatible Assignments": "تکالیف ناسازگار با پرونده",
    "Individual Subject Breakdown": "تفکیک وضعیت به ازای هر درس",
})

with open(fa_path, "w", encoding="utf-8") as f:
    json.dump(fa, f, ensure_ascii=False, indent=2)
print("Part 3 complete.")
