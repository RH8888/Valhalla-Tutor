import json

translations = {
  # Placeholders
  "e.g. 150": "مثلاً ۱۵۰",
  "e.g. دفترچه عمومی یا دفترچه ۱": "مثلاً دفترچه عمومی یا دفترچه ۱",
  "e.g. 90": "مثلاً ۹۰",
  "e.g. استاد ملاک‌پور, استاد یحیوی": "مثلاً استاد ملاک‌پور، استاد یحیوی",
  "e.g. زمان‌بندی فیزیک کم آمد": "مثلاً زمان‌بندی فیزیک کم آمد",
  "e.g. Student requested later slot": "مثلاً دانش‌آموز درخواست زمان دیرتر داشت",
  "Track goals, target exams, or specializations...": "اهداف رشته، آزمون‌های هدف یا گرایش‌ها...",
  "e.g. Sprint 3 — Nov 15 to Nov 28": "مثلاً دوره ۳ — ۱۵ آبان تا ۲۸ آبان",
  "— %": "— ٪",
  "e.g. این آزمون شامل ۲ دفترچه عمومی و اختصاصی است. نمره منفی لحاظ می‌شود.": "مثلاً این آزمون شامل ۲ دفترچه عمومی و اختصاصی است. نمره منفی لحاظ می‌شود.",
  "e.g. 1423124431... or 1,4,2,3...": "مثلاً ۱،۴،۲،۳... یا ۱۴۲۳۱۲۴۴۳۱...",
  "e.g. آزمون قلم‌چی - ۱۸ آبان": "مثلاً آزمون قلم‌چی - ۱۸ آبان",
  "e.g. Ali Rezaei": "مثلاً علی رضایی",
  "New group title (e.g. ریاضیات کنکور)": "عنوان گروه جدید (مثلاً ریاضیات کنکور)",
  "Brief summary of syllabus or grade focus...": "خلاصه سرفصل یا تمرکز پایه تحصیلی...",
  "Reply to {{ student.full_name }}... (Enter to send, Shift+Enter for newline)": "پاسخ به {{ student.full_name }}... (Enter برای ارسال، Shift+Enter برای خط بعد)",
  "e.g. 1420": "مثلاً ۱۴۲۰",
  "Valhalla Center, Room 204": "مرکز والهالا، اتاق ۲۰۴",
  "60 (leave empty if untimed)": "۶۰ (در صورت بدون زمان بودن خالی بگذارید)",
  "e.g. ali@example.com": "مثلاً ali@example.com",
  "e.g. 60": "مثلاً ۶۰",
  "e.g. علوم انسانی, المپیاد زیست": "مثلاً علوم انسانی، المپیاد زیست",
  "e.g. نوبت اول - آذرماه": "مثلاً نوبت اول - آذرماه",
  "e.g. 45": "مثلاً ۴۵",
  "e.g. alirezaei": "مثلاً alirezaei",
  "e.g. قلم‌چی - آزمون‌های آزمایشی": "مثلاً قلم‌چی - آزمون‌های آزمایشی",
  "e.g. Review yesterday": "مثلاً مرور دیروز",
  "https://meet.google.com/...": "https://meet.google.com/...",
  "Topics to cover, homework review, student progress notes...": "مباحث جلسه، بررسی تکالیف، یادداشت‌های پیشرفت دانش‌آموز...",
  "1": "۱",
  "e.g. زیست‌شناسی جامع خیلی سبز": "مثلاً زیست‌شناسی جامع خیلی سبز",
  "e.g. آزمون شبیه‌ساز کنکور تجربی - جامع زیست و شیمی": "مثلاً آزمون شبیه‌ساز کنکور تجربی - جامع زیست و شیمی",
  "Search by student name or username...": "جستجو بر اساس نام یا نام کاربری دانش‌آموز...",
  "Optional notes or instructions for this exam series": "یادداشت‌ها یا دستورالعمل‌های اختیاری برای این مجموعه آزمون",
  "e.g. ریاضی, حسابان, فیزیک": "مثلاً ریاضی، حسابان، فیزیک",
  "e.g. فصل ۱: تابع": "مثلاً فصل ۱: تابع",
  "e.g. tutor or student@valhalla.local": "مثلاً tutor یا student@valhalla.local",
  "e.g. نتایج آزمون جامع ورودی به دوره مشاوره": "مثلاً نتایج آزمون جامع ورودی به دوره مشاوره",
  "60": "۶۰",
  "e.g. فصل ۱: گوارش": "مثلاً فصل ۱: گوارش",
  "e.g. ریاضی جامع کنکور ۱۴۰۳": "مثلاً ریاضی جامع کنکور ۱۴۰۳",
  "0.0": "۰.۰",
  "Type your message... (Enter to send, Shift+Enter for newline)": "پیام خود را بنویسید... (Enter برای ارسال، Shift+Enter برای خط بعد)",
  "Specific instructions or problem numbers...": "دستورالعمل‌های خاص یا شماره سوالات...",

  # Titles
  "Back to conversations": "بازگشت به گفتگوها",
  "Add meeting on {{ d_str }}": "افزودن جلسه در {{ d_str }}",
  "Meeting Reminders": "یادآور جلسات",
  "Move Down": "انتقال به پایین",
  "Take this practice exam again": "شرکت مجدد در این آزمون تمرینی",
  "Read{% if msg.read_at %} {{ msg.read_at | chat_time(current_user.timezone) }}{% endif %}": "خوانده شده{% if msg.read_at %} {{ msg.read_at | chat_time(current_user.timezone) }}{% endif %}",
  "تغییر به فارسی": "تغییر به فارسی",
  "Suggested from historical data": "پیشنهاد شده از روی سوابق",
  "Extend to date": "تمدید تا تاریخ",
  "Recalculate unadjusted slots without losing your manual edits": "محاسبه مجدد زمان‌های تنظیم‌نشده بدون حذف ویرایش‌های دستی شما",
  "Switch to English": "تغییر به انگلیسی",
  "Click to assign student grade in profile": "برای تعیین پایه دانش‌آموز در پروفایل کلیک کنید",
  "Dismiss reminder": "بستن یادآور",
  "Move Up": "انتقال به بالا",
  "Extend recurring occurrences": "تمدید نوبت‌های تکرارشونده",

  # Confirms
  "Dismiss this assignment? Future unsubmitted exam occurrences will be removed for this student, but all past completed results will be strictly preserved.": "آیا این انتساب لغو شود؟ نوبت‌های آزمون آینده ارسال‌نشده برای این دانش‌آموز حذف خواهند شد، اما تمامی نتایج ثبت‌شده گذشته محفوظ می‌مانند.",
  "Delete chapter {{ ch.name }}?": "آیا فصل {{ ch.name }} حذف شود؟",
  "Skip this exam occurrence (mark as No Exam)?": "آیا از این نوبت آزمون صرف‌نظر شود (علامت‌گذاری بدون آزمون)؟",
  "Remove this grade/track configuration?": "آیا این پیکربندی پایه/رشته حذف شود؟",
  "Remove {{ sub.name }} from this track?": "آیا درس {{ sub.name }} از این رشته حذف شود؟",
  "Cancel this meeting?": "آیا این جلسه لغو شود؟",
  "Deactivating this student will immediately revoke all their active sessions. Proceed?": "غیرفعال کردن این دانش‌آموز بلافاصله کلیه نشست‌های فعال وی را خاتمه می‌دهد. آیا ادامه می‌دهید؟",
  "Warning: Once you submit this booklet, your answers will be PERMANENTLY LOCKED and cannot be edited. Are you sure you want to proceed?": "هشدار: پس از ارسال این دفترچه، پاسخ‌های شما برای همیشه قفل شده و قابل ویرایش نخواهند بود. آیا مطمئن هستید؟",
  "Delete entire course {{ course.name }} and all its chapters?": "آیا کل دوره {{ course.name }} و تمام فصول آن حذف شود؟",
  "Delete track {{ track.name }}? This will fail if students are assigned to it.": "آیا رشته {{ track.name }} حذف شود؟ در صورتی که دانش‌آموزی به آن منتسب باشد، عملیات متوقف می‌شود."
}

with open("app/locales/fa.json", "r", encoding="utf-8") as f:
    fa = json.load(f)

fa.update(translations)

with open("app/locales/fa.json", "w", encoding="utf-8") as f:
    json.dump(fa, f, ensure_ascii=False, indent=2)

with open("app/locales/en.json", "r", encoding="utf-8") as f:
    en = json.load(f)

for k in translations:
    if k not in en:
        en[k] = k

with open("app/locales/en.json", "w", encoding="utf-8") as f:
    json.dump(en, f, ensure_ascii=False, indent=2)

print(f"Added {len(translations)} attribute translations. Total in fa.json: {len(fa)}")
