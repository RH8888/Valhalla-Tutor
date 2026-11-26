import uuid
import pytest
from sqlalchemy import create_engine, text
from app.core.config import settings
from app.models.base import Base
from app.models.user import User, UserRole
from app.services.auth_service import create_session, get_user_and_session_by_token
from app.services.tutor_provision import provision_tutor


def is_postgres_available() -> bool:
    """Check if PostgreSQL server is running and accessible."""
    try:
        engine = create_engine(settings.sync_database_url, connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.mark.skipif(not is_postgres_available(), reason="PostgreSQL service not reachable; run docker compose up db to execute PostgreSQL integration tests.")
def test_postgres_schema_and_session_lifecycle():
    """Integration test verifying schema creation and session operations directly on PostgreSQL."""
    pg_engine = create_engine(settings.sync_database_url)
    Base.metadata.create_all(bind=pg_engine)

    from sqlalchemy.orm import Session
    from app.core.security import hash_password
    with Session(pg_engine) as session:
        # Create temp tutor
        test_uname = f"pg_tutor_{uuid.uuid4().hex[:8]}"
        tutor = User(
            id=uuid.uuid4(),
            username=test_uname,
            hashed_password=hash_password("PgPassword123!"),
            role=UserRole.TUTOR,
            full_name="Postgres Tutor",
            timezone="Asia/Tehran",
        )
        session.add(tutor)
        session.commit()
        assert tutor.role == UserRole.TUTOR

        # Create session
        token, s_rec = create_session(session, tutor)
        assert s_rec.user_id == tutor.id

        # Validate session retrieval
        u, s = get_user_and_session_by_token(session, token)
        assert u is not None
        assert u.username == test_uname

        # Cleanup
        session.delete(s_rec)
        session.delete(tutor)
        session.commit()



@pytest.mark.skipif(not is_postgres_available(), reason="PostgreSQL service not reachable; run docker compose up db to execute PostgreSQL integration tests.")
def test_postgres_meeting_and_reminders_lifecycle():
    """Verify meeting models, history, and reminders against live PostgreSQL 16."""
    from datetime import date, time
    from sqlalchemy.orm import Session
    from app.models.meeting import MeetingType, MeetingStatus, TutorMeeting
    from app.services.meeting_service import (
        create_meeting,
        reschedule_meeting,
        update_meeting_status,
        get_due_reminders,
        dismiss_reminder,
    )
    from app.services.user_service import create_student

    pg_engine = create_engine(settings.sync_database_url)
    with Session(pg_engine) as session:
        from app.core.security import hash_password
        tutor = User(
            id=uuid.uuid4(),
            username=f"tutor_{uuid.uuid4().hex[:6]}",
            hashed_password=hash_password("PgPassword123!"),
            role=UserRole.TUTOR,
            full_name="Postgres Meeting Tutor",
            timezone="Asia/Tehran",
        )
        session.add(tutor)
        session.commit()
        student = create_student(
            db=session,
            username=f"stu_{uuid.uuid4().hex[:6]}",
            full_name="Postgres Student",
            password="StuPassword123!",
        )

        # 1. Create meeting with reminder on PostgreSQL
        meeting = create_meeting(
            db=session,
            tutor=tutor,
            student_id=student.id,
            meeting_date=date(2026, 12, 1),
            start_time_obj=time(14, 0),
            duration_minutes=60,
            meeting_type=MeetingType.ONLINE,
            meeting_url="https://meet.pg.local/123",
            reminder_minutes=30,
        )
        assert meeting.id is not None
        assert meeting.status == MeetingStatus.SCHEDULED

        # 2. Reschedule meeting
        updated = reschedule_meeting(
            db=session,
            meeting_id=meeting.id,
            tutor=tutor,
            new_date=date(2026, 12, 1),
            new_time_obj=time(16, 0),
            new_duration_minutes=90,
            reason="Postgres reschedule test",
        )
        assert updated.duration_minutes == 90
        assert len(updated.reschedule_history) == 1

        # 3. Clean up
        session.delete(meeting)
        session.delete(student)
        session.delete(tutor)
        session.commit()



@pytest.mark.skipif(not is_postgres_available(), reason="PostgreSQL service not reachable; run docker compose up db to execute PostgreSQL integration tests.")
def test_postgres_concurrent_booklet_add_vs_attempt_start():
    """Verify PostgreSQL row locks serialize booklet additions against starting practice attempts."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy.orm import Session
    from app.models.practice_exam import PracticeExam, PracticeExamBooklet, StudentPracticeAttempt
    from app.models.subject import Subject
    from app.models.track import AcademicTrack
    from app.services.academic_service import create_subject, create_track
    from app.services.practice_exam_service import (
        PracticeExamValidationError,
        add_practice_exam_booklet,
        configure_practice_exam_questions,
        create_practice_exam,
        start_practice_attempt,
    )
    from app.services.user_service import create_student

    pg_engine = create_engine(settings.sync_database_url, pool_size=5, max_overflow=5)
    Base.metadata.create_all(bind=pg_engine)

    exam_id = student_id = sub_id = track_id = None
    try:
        with Session(pg_engine) as seed:
            sub = create_subject(seed, name=f"PG_PE_Sub_{uuid.uuid4().hex[:6]}", grades=["11"])
            track = create_track(seed, name=f"PG_PE_Track_{uuid.uuid4().hex[:6]}", subject_ids=[sub.id])
            student = create_student(
                seed,
                username=f"pg_pe_{uuid.uuid4().hex[:6]}",
                full_name="PG Practice Student",
                password="StuPassword123!",
                grade="11",
            )
            student.academic_track_id = track.id
            seed.commit()
            exam = create_practice_exam(seed, title="PG Race Practice", grade="11", academic_track_id=track.id)
            add_practice_exam_booklet(seed, exam.id, "Booklet 1", "b1.pdf", "b1.pdf", 1, 2, duration_minutes=15)
            configure_practice_exam_questions(
                seed,
                exam.id,
                [
                    {"question_number": 1, "correct_choice": 1, "subject_id": sub.id},
                    {"question_number": 2, "correct_choice": 2, "subject_id": sub.id},
                ],
            )
            exam_id, student_id, sub_id, track_id = exam.id, student.id, sub.id, track.id

        barrier = threading.Barrier(2)

        def run_add_booklet():
            with Session(pg_engine) as s:
                barrier.wait(timeout=10)
                try:
                    add_practice_exam_booklet(s, exam_id, "Booklet 2", "b2.pdf", "b2.pdf", 3, 4, duration_minutes=15)
                    return "added"
                except PracticeExamValidationError:
                    return "rejected"

        def run_start_attempt():
            with Session(pg_engine) as s:
                stu = s.get(User, student_id)
                barrier.wait(timeout=10)
                start_practice_attempt(s, stu, exam_id)
                return "started"

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_add = pool.submit(run_add_booklet)
            f_start = pool.submit(run_start_attempt)
            add_res = f_add.result(timeout=15)
            start_res = f_start.result(timeout=15)

        assert start_res == "started"
        assert add_res in ("added", "rejected")

        with Session(pg_engine) as check:
            b_count = check.query(PracticeExamBooklet).filter_by(practice_exam_id=exam_id).count()
            a_count = check.query(StudentPracticeAttempt).filter_by(practice_exam_id=exam_id).count()
            assert a_count == 1
            assert (add_res == "added" and b_count == 2) or (add_res == "rejected" and b_count == 1)
            # Any booklet addition after attempt existence is strictly blocked
            with pytest.raises(PracticeExamValidationError):
                add_practice_exam_booklet(check, exam_id, "Booklet Late", "b3.pdf", "b3.pdf", 5, 6, duration_minutes=10)
    finally:
        with Session(pg_engine) as cleanup:
            if exam_id:
                ex = cleanup.get(PracticeExam, exam_id)
                if ex:
                    cleanup.delete(ex)
            if student_id:
                st = cleanup.get(User, student_id)
                if st:
                    cleanup.delete(st)
            if track_id:
                tr = cleanup.get(AcademicTrack, track_id)
                if tr:
                    cleanup.delete(tr)
            if sub_id:
                sb = cleanup.get(Subject, sub_id)
                if sb:
                    cleanup.delete(sb)
            cleanup.commit()


@pytest.mark.skipif(not is_postgres_available(), reason="PostgreSQL service not reachable; run docker compose up db to execute PostgreSQL integration tests.")
def test_postgres_concurrent_exam_review_vs_student_update():
    """Verify PostgreSQL row locks serialize tutor review lock vs concurrent student result edit."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from datetime import date
    from sqlalchemy.orm import Session
    from app.core.security import hash_password
    from app.models.exam import Exam, StudentExamResult
    from app.models.subject import Subject
    from app.models.track import AcademicTrack
    from app.services.academic_service import assign_student_track, create_subject, create_track
    from app.services.exam_service import (
        ExamValidationError,
        create_exam,
        create_exam_session,
        mark_exam_result_reviewed,
        submit_student_exam_result,
        update_student_exam_result,
    )
    from app.services.user_service import create_student

    pg_engine = create_engine(settings.sync_database_url, pool_size=5, max_overflow=5)
    Base.metadata.create_all(bind=pg_engine)

    exam_id = student_id = tutor_id = sub_id = track_id = result_id = None
    try:
        with Session(pg_engine) as seed:
            tutor = User(
                id=uuid.uuid4(),
                username=f"pg_ex_t_{uuid.uuid4().hex[:6]}",
                hashed_password=hash_password("PgPassword123!"),
                role=UserRole.TUTOR,
                full_name="PG Exam Tutor",
                timezone="Asia/Tehran",
            )
            seed.add(tutor)
            sub = create_subject(seed, name=f"PG_ExSub_{uuid.uuid4().hex[:6]}", grades=["11"])
            track = create_track(seed, name=f"PG_ExTrack_{uuid.uuid4().hex[:6]}", subject_ids=[sub.id])
            student = create_student(
                seed,
                username=f"pg_ex_s_{uuid.uuid4().hex[:6]}",
                full_name="PG Exam Student",
                password="StuPassword123!",
                grade="11",
            )
            assign_student_track(seed, student.id, track.id)
            exam = create_exam(seed, title="PG Race Exam")
            sess = create_exam_session(seed, exam.id, date(2026, 12, 1), track_subjects_map={track.id: [sub.id]})
            res = submit_student_exam_result(
                seed,
                student=student,
                exam_session_id=sess.id,
                subject_data=[{"subject_id": sub.id, "correct_answers": 5, "incorrect_answers": 0, "percentage": 50.0}],
            )
            exam_id, student_id, tutor_id, sub_id, track_id, result_id = (
                exam.id, student.id, tutor.id, sub.id, track.id, res.id
            )

        barrier = threading.Barrier(2)

        def run_review():
            with Session(pg_engine) as s:
                barrier.wait(timeout=10)
                mark_exam_result_reviewed(s, result_id, actor_id=tutor_id)
                return "reviewed"

        def run_student_edit():
            with Session(pg_engine) as s:
                stu = s.get(User, student_id)
                barrier.wait(timeout=10)
                try:
                    update_student_exam_result(
                        s,
                        student=stu,
                        result_id=result_id,
                        subject_data=[{"subject_id": sub_id, "correct_answers": 10, "incorrect_answers": 0, "percentage": 100.0}],
                    )
                    return "updated"
                except ExamValidationError:
                    return "blocked"

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_rev = pool.submit(run_review)
            f_upd = pool.submit(run_student_edit)
            assert f_rev.result(timeout=15) == "reviewed"
            upd_res = f_upd.result(timeout=15)

        assert upd_res in ("updated", "blocked")
        with Session(pg_engine) as check:
            final_res = check.get(StudentExamResult, result_id)
            stu_chk = check.get(User, student_id)
            assert final_res is not None and final_res.is_reviewed is True
            # Regardless of which committed first, once reviewed, further student edits are strictly blocked
            with pytest.raises(ExamValidationError):
                update_student_exam_result(
                    check,
                    student=stu_chk,
                    result_id=result_id,
                    subject_data=[{"subject_id": sub_id, "correct_answers": 9, "incorrect_answers": 1, "percentage": 85.0}],
                )
    finally:
        with Session(pg_engine) as cleanup:
            if exam_id:
                ex = cleanup.get(Exam, exam_id)
                if ex:
                    cleanup.delete(ex)
            if student_id:
                st = cleanup.get(User, student_id)
                if st:
                    cleanup.delete(st)
            if tutor_id:
                tu = cleanup.get(User, tutor_id)
                if tu:
                    cleanup.delete(tu)
            if track_id:
                tr = cleanup.get(AcademicTrack, track_id)
                if tr:
                    cleanup.delete(tr)
            if sub_id:
                sb = cleanup.get(Subject, sub_id)
                if sb:
                    cleanup.delete(sb)
            cleanup.commit()


@pytest.mark.skipif(not is_postgres_available(), reason="PostgreSQL service not reachable; run docker compose up db to execute PostgreSQL integration tests.")
def test_postgres_concurrent_plan_races_and_audit_restrict():
    """Verify PostgreSQL locks for complete/delete, archive/complete/undo, and native FK RESTRICT."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from datetime import date
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session
    from app.core.security import hash_password
    from app.models.plan import CompletionAuditLog, PlanAssignment, StudyPlan, TaskType
    from app.models.subject import Subject
    from app.models.track import AcademicTrack
    from app.services.academic_service import assign_student_track, create_subject, create_track
    from app.services.plan_service import (
        AssignmentNotFoundError,
        PlanValidationError,
        archive_study_plan,
        complete_assignment,
        create_assignment,
        create_study_plan,
        delete_assignment,
        delete_study_plan,
        publish_study_plan,
        reset_assignment_completion,
        undo_assignment_completion,
    )
    from app.services.user_service import create_student

    pg_engine = create_engine(settings.sync_database_url, pool_size=6, max_overflow=6)
    Base.metadata.create_all(bind=pg_engine)

    tutor_id = student_id = sub_id = track_id = None
    try:
        with Session(pg_engine) as seed:
            tutor = User(
                id=uuid.uuid4(),
                username=f"pg_pl_t_{uuid.uuid4().hex[:6]}",
                hashed_password=hash_password("PgPassword123!"),
                role=UserRole.TUTOR,
                full_name="PG Plan Tutor",
                timezone="Asia/Tehran",
            )
            seed.add(tutor)
            sub = create_subject(seed, name=f"PG_PlSub_{uuid.uuid4().hex[:6]}", grades=["11"])
            track = create_track(seed, name=f"PG_PlTrack_{uuid.uuid4().hex[:6]}", subject_ids=[sub.id])
            student = create_student(
                seed,
                username=f"pg_pl_s_{uuid.uuid4().hex[:6]}",
                full_name="PG Plan Student",
                password="StuPassword123!",
                grade="11",
            )
            assign_student_track(seed, student.id, track.id)

            # Plan 1: complete vs delete race
            plan1 = create_study_plan(seed, student.id, tutor.id, date(2026, 12, 1), title="PG Race Plan 1")
            a1 = create_assignment(seed, plan1.id, plan1.start_date, sub.id, TaskType.CUSTOM, 30, title="A1", tutor_id=tutor.id)
            publish_study_plan(seed, plan1.id, tutor_id=tutor.id)
            tutor_id, student_id, sub_id, track_id = tutor.id, student.id, sub.id, track.id
            plan1_id, a1_id = plan1.id, a1.id

        barrier1 = threading.Barrier(2)

        def race_complete():
            with Session(pg_engine) as s:
                barrier1.wait(timeout=10)
                try:
                    complete_assignment(s, a1_id, student_id, actual_duration_minutes=20)
                    return "completed"
                except (AssignmentNotFoundError, PlanValidationError):
                    return "missing_or_blocked"

        def race_delete():
            with Session(pg_engine) as s:
                barrier1.wait(timeout=10)
                try:
                    delete_assignment(s, a1_id, tutor_id=tutor_id)
                    return "deleted"
                except (PlanValidationError, AssignmentNotFoundError):
                    return "blocked"

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_c = pool.submit(race_complete)
            f_d = pool.submit(race_delete)
            res_c = f_c.result(timeout=15)
            res_d = f_d.result(timeout=15)

        with Session(pg_engine) as check1:
            rem_a1 = check1.get(PlanAssignment, a1_id)
            if rem_a1 is None:
                assert res_d == "deleted" and res_c == "missing_or_blocked"
                assert check1.query(CompletionAuditLog).filter_by(assignment_id=a1_id).count() == 0
            else:
                assert rem_a1.is_completed is True and res_c == "completed" and res_d == "blocked"
                assert check1.query(CompletionAuditLog).filter_by(assignment_id=a1_id).count() == 1

            # Archive vs complete/undo race + native FK RESTRICT verification on plan2
            plan2 = create_study_plan(check1, student_id, tutor_id, date(2026, 12, 15), title="PG Race Plan 2")
            a_pend = create_assignment(check1, plan2.id, plan2.start_date, sub_id, TaskType.CUSTOM, 30, title="Pend", tutor_id=tutor_id)
            a_done = create_assignment(check1, plan2.id, plan2.start_date, sub_id, TaskType.CUSTOM, 25, title="Done", tutor_id=tutor_id)
            publish_study_plan(check1, plan2.id, tutor_id=tutor_id)
            complete_assignment(check1, a_done.id, student_id, actual_duration_minutes=25)
            plan2_id, a_pend_id, a_done_id = plan2.id, a_pend.id, a_done.id

        barrier2 = threading.Barrier(3)

        def race_archive():
            with Session(pg_engine) as s:
                barrier2.wait(timeout=10)
                archive_study_plan(s, plan2_id, tutor_id=tutor_id)
                return "archived"

        def race_pend_complete():
            with Session(pg_engine) as s:
                barrier2.wait(timeout=10)
                try:
                    complete_assignment(s, a_pend_id, student_id, actual_duration_minutes=30)
                    return "completed"
                except PlanValidationError:
                    return "blocked"

        def race_done_undo():
            with Session(pg_engine) as s:
                barrier2.wait(timeout=10)
                try:
                    undo_assignment_completion(s, a_done_id, student_id)
                    return "undone"
                except PlanValidationError:
                    return "blocked"

        with ThreadPoolExecutor(max_workers=3) as pool:
            f_arch = pool.submit(race_archive)
            f_pc = pool.submit(race_pend_complete)
            f_du = pool.submit(race_done_undo)
            assert f_arch.result(timeout=15) == "archived"
            f_pc.result(timeout=15)
            f_du.result(timeout=15)

        with Session(pg_engine) as check2:
            with pytest.raises(PlanValidationError):
                complete_assignment(check2, a_pend_id, student_id, actual_duration_minutes=30)
            with pytest.raises(PlanValidationError):
                undo_assignment_completion(check2, a_done_id, student_id)
            with pytest.raises(PlanValidationError):
                reset_assignment_completion(check2, a_done_id, tutor_id, note="post-archive")

            # Test native PostgreSQL FK RESTRICT on reset assignment + draft study plan
            plan3 = create_study_plan(check2, student_id, tutor_id, date(2027, 1, 1), title="PG Audit Restrict Plan")
            a3 = create_assignment(check2, plan3.id, plan3.start_date, sub_id, TaskType.CUSTOM, 20, title="A3", tutor_id=tutor_id)
            complete_assignment(check2, a3.id, student_id, actual_duration_minutes=20)
            reset_assignment_completion(check2, a3.id, tutor_id, note="reset before delete attempt")
            with pytest.raises(PlanValidationError):
                delete_assignment(check2, a3.id, tutor_id=tutor_id)
            with pytest.raises(PlanValidationError):
                delete_study_plan(check2, plan3.id, tutor_id=tutor_id)
            with pytest.raises(IntegrityError):
                check2.execute(text("DELETE FROM plan_assignments WHERE id = :id"), {"id": a3.id})
                check2.flush()
            check2.rollback()
    finally:
        with Session(pg_engine) as cleanup:
            if student_id:
                cleanup.execute(text("DELETE FROM completion_audit_logs WHERE student_id = :sid"), {"sid": student_id})
                cleanup.execute(text("DELETE FROM plan_assignments WHERE student_id = :sid"), {"sid": student_id})
                cleanup.execute(text("DELETE FROM study_plans WHERE student_id = :sid"), {"sid": student_id})
                cleanup.commit()
                st = cleanup.get(User, student_id)
                if st:
                    cleanup.delete(st)
            if tutor_id:
                tu = cleanup.get(User, tutor_id)
                if tu:
                    cleanup.delete(tu)
            if track_id:
                tr = cleanup.get(AcademicTrack, track_id)
                if tr:
                    cleanup.delete(tr)
            if sub_id:
                sb = cleanup.get(Subject, sub_id)
                if sb:
                    cleanup.delete(sb)
            cleanup.commit()
