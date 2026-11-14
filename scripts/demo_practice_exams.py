"""Generate demo practice exams, booklets with PDFs, questions, and assignments."""
from sqlalchemy.orm import Session
from app.models.practice_exam import (
    PracticeExam,
    PracticeExamBooklet,
    PracticeExamReportingGroup,
    PracticeExamQuestion,
    PracticeExamAssignment,
)
from app.models.track import AcademicTrack
from app.models.user import User
from scripts.demo_pdf import save_demo_pdf


def setup_demo_practice_exams(
    db: Session,
    tracks: dict[str, AcademicTrack],
    students: list[User],
) -> list[PracticeExam]:
    math_track = tracks["ریاضی"]
    exp_track = tracks["تجربی"]

    exam_specs = [
        {
            "title": "[دمو] آزمون مبحثی حسابان و فیزیک یازدهم",
            "grade": "11",
            "track": math_track,
            "b1_title": "دفترچه ۱: حسابان و ریاضیات پایه",
            "b2_title": "دفترچه ۲: فیزیک و شیمی",
        },
        {
            "title": "[دمو] آزمون جامع شبیه‌ساز کنکور تجربی",
            "grade": "12",
            "track": exp_track,
            "b1_title": "دفترچه ۱: زیست‌شناسی تخصصی",
            "b2_title": "دفترچه ۲: فیزیک و شیمی تجربی",
        },
    ]

    exams = []
    for spec in exam_specs:
        exam = db.query(PracticeExam).filter(PracticeExam.title == spec["title"]).first()
        if not exam:
            exam = PracticeExam(
                title=spec["title"],
                description=f"آزمون تمرینی و شبیه‌ساز آنلاین برای دانش‌آموزان پایه {spec['grade']} {spec['track'].name}",
                grade=spec["grade"],
                academic_track_id=spec["track"].id,
                is_timed=True,
                is_active=True,
            )
            db.add(exam)
            db.flush()

            # Reporting groups
            rg1 = PracticeExamReportingGroup(practice_exam_id=exam.id, title="گروه تخصصی ۱")
            rg2 = PracticeExamReportingGroup(practice_exam_id=exam.id, title="گروه تخصصی ۲")
            db.add_all([rg1, rg2])
            db.flush()

            # Booklets with PDFs
            b1_path, b1_orig = save_demo_pdf("practice_booklets", f"booklet_{exam.id.hex[:6]}_1", spec["b1_title"])
            b2_path, b2_orig = save_demo_pdf("practice_booklets", f"booklet_{exam.id.hex[:6]}_2", spec["b2_title"])

            b1 = PracticeExamBooklet(
                practice_exam_id=exam.id,
                order_index=1,
                title=spec["b1_title"],
                pdf_file_path=b1_path,
                pdf_file_name=b1_orig,
                question_start=1,
                question_end=20,
                duration_minutes=30,
            )
            b2 = PracticeExamBooklet(
                practice_exam_id=exam.id,
                order_index=2,
                title=spec["b2_title"],
                pdf_file_path=b2_path,
                pdf_file_name=b2_orig,
                question_start=21,
                question_end=40,
                duration_minutes=35,
            )
            db.add_all([b1, b2])
            db.flush()

            # Questions 1 to 40
            track_subs = spec["track"].subjects
            sub1 = track_subs[0]
            sub2 = track_subs[1] if len(track_subs) > 1 else sub1
            for q_num in range(1, 41):
                correct = ((q_num * 3) % 4) + 1  # cycle 1..4
                target_sub = sub1 if q_num <= 20 else sub2
                target_rg = rg1 if q_num <= 20 else rg2
                db.add(PracticeExamQuestion(
                    practice_exam_id=exam.id,
                    question_number=q_num,
                    correct_choice=correct,
                    subject_id=target_sub.id,
                    reporting_group_id=target_rg.id,
                ))

            # Assignments to matching grade & track students
            matching = [s for s in students if s.grade == spec["grade"] and s.academic_track_id == spec["track"].id]
            for s in matching:
                db.add(PracticeExamAssignment(practice_exam_id=exam.id, student_id=s.id))

        exams.append(exam)

    db.flush()
    return exams
