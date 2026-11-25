import json
import re
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.i18n import (
    format_jalali,
    format_persian_currency,
    format_persian_duration,
    format_persian_number,
    format_persian_percent,
    gregorian_to_jalali,
    jalali_to_gregorian,
    translate_role,
    translate_status,
    translate_weekday,
)
from app.core.security import hash_password
from app.models.book import Book, BookChapter
from app.models.course import Course, CourseChapter
from app.models.exam import Exam, ExamGradeTrackConfig, ExamSession
from app.models.plan import PlanAssignment, PlanStatus, StudyPlan, TaskType
from app.models.subject import Subject
from app.models.track import AcademicTrack
from app.models.user import User, UserRole
from app.services.auth_service import create_session


def _seed_sample_data(db: Session):
    tutor = User(
        username="tutor_i18n",
        email="tutor_i18n@example.com",
        full_name="مشاور نمونه",
        hashed_password=hash_password("Pass1234!"),
        role=UserRole.TUTOR,
        is_active=True,
    )
    track = AcademicTrack(name="ریاضی فیزیک", is_default=True)
    subj = Subject(name="حسابان")
    track.subjects.append(subj)
    db.add_all([tutor, track, subj])
    db.flush()

    student = User(
        username="student_i18n",
        email="student_i18n@example.com",
        full_name="دانش‌آموز نمونه",
        hashed_password=hash_password("Pass1234!"),
        role=UserRole.STUDENT,
        is_active=True,
        grade="12",
        academic_track_id=track.id,
    )
    db.add(student)
    db.flush()

    course = Course(subject_id=subj.id, teacher_name="استاد نمونه", name="دوره حسابان", grade="12")
    book = Book(subject_id=subj.id, title="کتاب تست حسابان", grade="12")
    db.add_all([course, book])
    db.flush()
    db.add_all([
        CourseChapter(course_id=course.id, name="فصل ۱", display_order=1, video_count=4),
        BookChapter(book_id=book.id, title="فصل ۱", display_order=1, test_count=40),
    ])

    today = date.today()
    plan = StudyPlan(
        student_id=student.id,
        tutor_id=tutor.id,
        title="برنامه آزمایشی",
        start_date=today,
        end_date=today + timedelta(days=6),
        status=PlanStatus.PUBLISHED,
    )
    db.add(plan)
    db.flush()
    db.add(
        PlanAssignment(
            study_plan_id=plan.id,
            student_id=student.id,
            subject_id=subj.id,
            scheduled_date=today,
            task_type=TaskType.CUSTOM,
            title="مطالعه",
            recommended_duration_minutes=45,
        )
    )

    exam = Exam(title="آزمون آزمایشی", is_active=True)
    db.add(exam)
    db.flush()
    db.add(ExamGradeTrackConfig(exam_id=exam.id, grade="12", track_id=track.id))
    esess = ExamSession(exam_id=exam.id, date=today, title="نوبت اول")
    db.add(esess)
    db.commit()
    return {
        "tutor": tutor,
        "student": student,
        "track": track,
        "subject": subj,
        "course": course,
        "book": book,
        "plan": plan,
        "exam": exam,
        "session": esess,
    }


def _login_client(client: TestClient, db: Session, user: User):
    raw_token, _ = create_session(db, user)
    client.cookies.set("valhalla_session", raw_token)
    client.base_url = "https://testserver"


def test_persian_locale_catalog_completeness():
    en = json.loads(Path("app/locales/en.json").read_text(encoding="utf-8"))
    fa = json.loads(Path("app/locales/fa.json").read_text(encoding="utf-8"))

    assert set(en.keys()) == set(fa.keys())

    pattern = re.compile(r"_\(\s*(['\"])(.*?)\1")
    missing = []
    for path in Path("app/templates").rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        for m in pattern.finditer(text):
            key = m.group(2)
            if key not in fa:
                missing.append(f"{path}:{key}")
    assert not missing, f"Missing translation keys in fa.json: {missing}"


def test_persian_formatting_and_jalali_helpers():
    assert gregorian_to_jalali(2024, 3, 20) == (1403, 1, 1)
    assert jalali_to_gregorian(1403, 1, 1) == (2024, 3, 20)
    assert format_jalali(date(2024, 3, 20)) == "۱ فروردین ۱۴۰۳"

    assert format_persian_number(12345) == "۱۲٬۳۴۵"
    assert format_persian_percent(78.5, decimals=1) == "۷۸٫۵٪"
    assert format_persian_duration(90, locale="fa") == "۱ ساعت و ۳۰ دقیقه"
    assert format_persian_currency(500000) == "۵۰۰٬۰۰۰ تومان"

    assert translate_role("TUTOR", "fa") == "مدرس"
    assert translate_role("STUDENT", "fa") == "دانش‌آموز"
    assert translate_status("SCHEDULED", "fa") == "زمان‌بندی‌شده"
    assert translate_weekday("Saturday", "fa") == "شنبه"


def test_language_switching_persists_and_clears_direction(client: TestClient):
    client.base_url = "https://testserver"

    # Default new user -> English LTR
    resp_default = client.get("/auth/login")
    assert resp_default.status_code == 200
    assert 'lang="en"' in resp_default.text
    assert 'dir="ltr"' in resp_default.text
    assert "Cookie" in resp_default.headers.get("Vary", "")

    # Switch to Persian while preserving query params
    next_url = "/tutor/videos?subject_id=123&tab=all"
    sw_fa = client.get(f"/set-language?lang=fa&redirect_url={quote(next_url, safe='')}", follow_redirects=False)
    assert sw_fa.status_code == 303
    assert sw_fa.headers["location"] == next_url
    assert client.cookies.get("valhalla_locale") == "fa"

    # Login page renders RTL Persian
    resp_fa = client.get("/auth/login")
    assert 'lang="fa"' in resp_fa.text
    assert 'dir="rtl"' in resp_fa.text
    assert "persian-ui.css" in resp_fa.text
    assert "ورود به سامانه" in resp_fa.text
    assert "سامانه آموزش وال\u200cهالا" in resp_fa.text

    # Switch back to English -> zero leftover RTL styling
    sw_en = client.get("/set-language?lang=en&redirect_url=/auth/login", follow_redirects=False)
    assert sw_en.status_code == 303
    assert client.cookies.get("valhalla_locale") == "en"

    resp_en = client.get("/auth/login")
    assert 'lang="en"' in resp_en.text
    assert 'dir="ltr"' in resp_en.text
    assert "Sign In" in resp_en.text
    assert "ورود به سامانه" not in resp_en.text

    # Open redirect protection
    ext = client.get("/set-language?lang=fa&redirect_url=https://evil.example/phish", follow_redirects=False)
    assert ext.headers["location"] == "/"

    # JSON response support
    js_resp = client.get("/set-language?lang=fa&format=json")
    assert js_resp.status_code == 200
    assert js_resp.json() == {"locale": "fa", "dir": "rtl"}


def test_language_persisted_across_login_refresh_and_logout(client: TestClient, db_session: Session):
    data = _seed_sample_data(db_session)
    client.base_url = "https://testserver"

    client.get("/set-language?lang=fa", follow_redirects=False)
    login_resp = client.post(
        "/auth/login",
        data={"identifier": data["student"].username, "password": "Pass1234!"},
        follow_redirects=False,
    )
    assert login_resp.status_code == 303
    assert client.cookies.get("valhalla_locale") == "fa"

    # Refresh / load student dashboard in Persian
    dash = client.get("/student/dashboard")
    assert dash.status_code == 200
    assert 'dir="rtl"' in dash.text
    assert 'lang="fa"' in dash.text

    # Logout preserves user's language cookie
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', dash.text)
    assert m is not None
    out = client.post("/auth/logout", data={"csrf_token": m.group(1)}, follow_redirects=False)
    assert out.status_code == 303
    assert client.cookies.get("valhalla_locale") == "fa"

    login_after = client.get("/auth/login")
    assert 'dir="rtl"' in login_after.text
    assert 'lang="fa"' in login_after.text


def test_persian_validation_and_http_errors(client: TestClient, db_session: Session):
    data = _seed_sample_data(db_session)
    client.base_url = "https://testserver"
    client.get("/set-language?lang=fa", follow_redirects=False)

    bad_login = client.post(
        "/auth/login",
        data={"identifier": data["tutor"].username, "password": "wrong-password"},
    )
    assert bad_login.status_code == 401
    assert "نام کاربری" in bad_login.text

    _login_client(client, db_session, data["tutor"])
    not_found = client.get("/tutor/students/00000000-0000-0000-0000-000000000000")
    assert not_found.status_code == 404
    assert "یافت نشد" in not_found.text


def test_calendar_saturday_first_and_all_routes_in_en_and_fa(client: TestClient, db_session: Session):
    data = _seed_sample_data(db_session)
    _login_client(client, db_session, data["tutor"])

    # Persian calendar must display Saturday (شنبه) first
    client.cookies.set("valhalla_locale", "fa")
    cal_fa = client.get("/tutor/calendar")
    assert cal_fa.status_code == 200
    assert 'dir="rtl"' in cal_fa.text
    sat_idx = cal_fa.text.find("شنبه")
    fri_idx = cal_fa.text.find("جمعه")
    assert sat_idx != -1 and fri_idx != -1 and sat_idx < fri_idx

    tutor_routes = [
        "/tutor/students",
        "/tutor/students/create",
        f"/tutor/students/{data['student'].id}",
        f"/tutor/students/{data['student'].id}/plans",
        f"/tutor/plans/{data['plan'].id}",
        "/tutor/tracks",
        "/tutor/subjects",
        "/tutor/videos",
        "/tutor/books",
        "/tutor/exams",
        f"/tutor/exams/{data['exam'].id}",
        f"/tutor/exams/sessions/{data['session'].id}",
        "/tutor/exams/bulk/overview",
        f"/tutor/exams/students/{data['student'].id}",
        "/tutor/practice-exams",
        "/tutor/historical-exams",
        "/tutor/messages",
        "/tutor/calendar",
        "/tutor/scheduler",
    ]
    for route in tutor_routes:
        client.cookies.set("valhalla_locale", "fa")
        r_fa = client.get(route)
        assert r_fa.status_code == 200, f"fa failed on {route}"
        assert 'dir="rtl"' in r_fa.text and 'lang="fa"' in r_fa.text
        no_script = re.sub(r"<script.*?</script>", "", r_fa.text, flags=re.S)
        assert not re.search(r"\b(?:text-left|text-right|right-0|left-0|ml-\d+|mr-\d+|pl-\d+|pr-\d+)\b", no_script), f"Physical CSS class remained in {route}"

        client.cookies.set("valhalla_locale", "en")
        r_en = client.get(route)
        assert r_en.status_code == 200, f"en failed on {route}"
        assert 'dir="ltr"' in r_en.text and 'lang="en"' in r_en.text

    # Student routes
    _login_client(client, db_session, data["student"])
    student_routes = [
        "/student/dashboard",
        "/student/plan",
        "/student/plans/history",
        f"/student/plans/{data['plan'].id}",
        "/student/history",
        "/student/curriculum",
        "/student/exams",
        "/student/exams/analytics",
        "/student/historical-exams",
        "/student/practice-exams",
        "/student/chat",
    ]
    for route in student_routes:
        client.cookies.set("valhalla_locale", "fa")
        r_fa = client.get(route)
        assert r_fa.status_code == 200, f"fa failed on {route}"
        assert 'dir="rtl"' in r_fa.text and 'lang="fa"' in r_fa.text

        client.cookies.set("valhalla_locale", "en")
        r_en = client.get(route)
        assert r_en.status_code == 200, f"en failed on {route}"
        assert 'dir="ltr"' in r_en.text and 'lang="en"' in r_en.text
