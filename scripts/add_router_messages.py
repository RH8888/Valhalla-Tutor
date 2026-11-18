import json

router_msgs = {
  "Exam results submitted successfully": "نتایج آزمون با موفقیت ثبت شد",
  "Exam results updated successfully": "نتایج آزمون با موفقیت بروزرسانی شد",
  "Booklet is not unlocked yet.": "دفترچه هنوز باز نشده است.",
  "Answers saved": "پاسخ‌ها با موفقیت ذخیره شد",
  "Booklet submitted. Proceeding to next booklet.": "دفترچه ارسال شد. در حال انتقال به دفترچه بعدی.",
  "Practice exam completed! Review your results below.": "آزمون تمرینی به پایان رسید! کارنامه خود را در زیر مشاهده فرمایید.",
  "Book created successfully": "کتاب تست با موفقیت ایجاد شد",
  "Book updated successfully": "کتاب تست با موفقیت بروزرسانی شد",
  "Chapter added successfully": "فصل با موفقیت اضافه شد",
  "Chapter deleted successfully": "فصل با موفقیت حذف شد",
  "Chapter updated successfully": "فصل با موفقیت بروزرسانی شد",
  "Book deleted successfully": "کتاب تست با موفقیت حذف شد",
  "Incompatible series assignment dismissed. Historical results were preserved.": "انتساب مجموعه ناسازگار لغو شد. نمرات تاریخی محفوظ ماندند.",
  "Result corrected successfully": "نمره با موفقیت تصحیح شد",
  "Result marked as reviewed": "کارنامه به عنوان بررسی‌شده ثبت شد",
  "Result reopened for review": "کارنامه جهت بازبینی مجدد باز شد",
  "Exam session scheduled successfully": "نوبت آزمون با موفقیت برنامه‌ریزی شد",
  "Exam definition created successfully": "تعریف آزمون با موفقیت ایجاد شد",
  "No students selected": "هیچ دانش‌آموزی انتخاب نشده است",
  "Exam series restored from archive": "مجموعه آزمون از آرشیو بازیابی شد",
  "Exam updated successfully": "آزمون با موفقیت بروزرسانی شد",
  "Grade and track reporting structure configured successfully": "ساختار کارنامه پایه و رشته با موفقیت تنظیم شد",
  "Grade/track configuration removed": "پیکربندی پایه/رشته حذف شد",
  "Occurrence deleted successfully": "نوبت آزمون با موفقیت حذف شد",
  "Exam series archived successfully": "مجموعه آزمون با موفقیت آرشیو شد",
  "Exam series deleted successfully": "مجموعه آزمون با موفقیت حذف شد",
  "Historical exam record not found.": "سوابق آزمون تاریخی یافت نشد.",
  "Historical exam result recorded successfully": "نتیجه آزمون پیشین با موفقیت ثبت شد",
  "Practice exam created. Now upload PDF booklets and configure questions.": "آزمون تمرینی ایجاد شد. اکنون فایل PDF دفترچه‌ها را بارگذاری و سوالات را تنظیم نمایید.",
  "Student account created": "حساب کاربری دانش‌آموز ایجاد شد",
  "Password cannot be empty": "کلمه عبور نمی‌تواند خالی باشد",
  "Academic track updated successfully": "رشته تحصیلی با موفقیت بروزرسانی شد",
  "Assignment completion was reset.": "وضعیت انجام تکلیف بازنشانی شد.",
  "Password reset successfully": "کلمه عبور با موفقیت بازنشانی شد",
  "Student subjects customized successfully": "دروس دانش‌آموز با موفقیت سفارشی‌سازی شد",
  "Student subjects reset to track defaults": "دروس دانش‌آموز به حالت پیش‌فرض رشته بازنشانی شد",
  "Subject deleted successfully": "درس با موفقیت حذف شد",
  "Academic track created successfully": "رشته تحصیلی با موفقیت ایجاد شد",
  "Subject added to track": "درس به رشته اضافه شد",
  "Subject removed from track": "درس از رشته حذف شد",
  "Academic track deleted successfully": "رشته تحصیلی با موفقیت حذف شد",
  "Course created successfully": "دوره آموزشی با موفقیت ایجاد شد",
  "Course updated successfully": "دوره آموزشی با موفقیت بروزرسانی شد",
  "Course deleted successfully": "دوره آموزشی با موفقیت حذف شد",
  "No occurrences selected": "هیچ نوبتی انتخاب نشده است",
  "Invalid credentials": "نام کاربری یا کلمه عبور نادرست است",
  "Invalid username or password": "نام کاربری یا کلمه عبور نامعتبر است",
  "You do not have access to this page": "شما به این صفحه دسترسی ندارید",
  "Unauthorized": "دسترسی غیرمجاز",
  "Session expired. Please log in again.": "نشست شما به پایان رسیده است. لطفاً دوباره وارد شوید."
}

with open("app/locales/fa.json", "r", encoding="utf-8") as f:
    fa = json.load(f)

fa.update(router_msgs)

with open("app/locales/fa.json", "w", encoding="utf-8") as f:
    json.dump(fa, f, ensure_ascii=False, indent=2)

with open("app/locales/en.json", "r", encoding="utf-8") as f:
    en = json.load(f)

for k in router_msgs:
    if k not in en:
        en[k] = k

with open("app/locales/en.json", "w", encoding="utf-8") as f:
    json.dump(en, f, ensure_ascii=False, indent=2)

print(f"Added {len(router_msgs)} router messages. Total in fa.json: {len(fa)}")
