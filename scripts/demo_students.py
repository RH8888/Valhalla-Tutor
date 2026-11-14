"""Demo students definition and generation."""
from sqlalchemy.orm import Session
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.models.track import AcademicTrack

DEMO_STUDENT_DEFS = [
    # Grade 10
    {"username": "demo_math_10_1", "full_name": "علی محمدی", "grade": "10", "track": "ریاضی", "profile": "top"},
    {"username": "demo_math_10_2", "full_name": "پارسا نادری", "grade": "10", "track": "ریاضی", "profile": "mid"},
    {"username": "demo_exp_10_1", "full_name": "سارا احمدی", "grade": "10", "track": "تجربی", "profile": "top"},
    {"username": "demo_exp_10_2", "full_name": "نیلوفر رضایی", "grade": "10", "track": "تجربی", "profile": "low"},
    # Grade 11
    {"username": "demo_math_11_1", "full_name": "امیرحسین کریمی", "grade": "11", "track": "ریاضی", "profile": "top"},
    {"username": "demo_math_11_2", "full_name": "سینا ابراهیمی", "grade": "11", "track": "ریاضی", "profile": "mid"},
    {"username": "demo_math_11_3", "full_name": "دانیال کاظمی", "grade": "11", "track": "ریاضی", "profile": "low"},
    {"username": "demo_exp_11_1", "full_name": "فاطمه حسینی", "grade": "11", "track": "تجربی", "profile": "top"},
    {"username": "demo_exp_11_2", "full_name": "مریم صادقی", "grade": "11", "track": "تجربی", "profile": "mid"},
    {"username": "demo_exp_11_3", "full_name": "آرمین رستمی", "grade": "11", "track": "تجربی", "profile": "low"},
    # Grade 12
    {"username": "demo_math_12_1", "full_name": "مهدی طاهری", "grade": "12", "track": "ریاضی", "profile": "top"},
    {"username": "demo_math_12_2", "full_name": "علیرضا قاسم‌پور", "grade": "12", "track": "ریاضی", "profile": "mid"},
    {"username": "demo_exp_12_1", "full_name": "زهرا موسوی", "grade": "12", "track": "تجربی", "profile": "top"},
    {"username": "demo_exp_12_2", "full_name": "پویا شریفی", "grade": "12", "track": "تجربی", "profile": "low"},
]

DEFAULT_PASSWORD = "DemoPass123!"


def ensure_demo_students(db: Session, tracks: dict[str, AcademicTrack]) -> list[User]:
    """Create or update demo students and return the list of User objects."""
    hashed_pwd = hash_password(DEFAULT_PASSWORD)
    students = []

    for d in DEMO_STUDENT_DEFS:
        user = db.query(User).filter(User.username == d["username"]).first()
        track_obj = tracks.get(d["track"])
        if not user:
            user = User(
                username=d["username"],
                email=f"{d['username']}@valhalla.test",
                hashed_password=hashed_pwd,
                role=UserRole.STUDENT,
                full_name=d["full_name"],
                grade=d["grade"],
                academic_track_id=track_obj.id if track_obj else None,
                is_active=True,
                timezone="Asia/Tehran",
            )
            db.add(user)
            db.flush()
        else:
            user.full_name = d["full_name"]
            user.grade = d["grade"]
            user.academic_track_id = track_obj.id if track_obj else None
            user.is_active = True
        students.append(user)

    db.flush()
    return students
