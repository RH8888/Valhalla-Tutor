"""SQLAlchemy database models."""
from app.models.base import Base
from app.models.user import User, UserRole
from app.models.session import UserSession
from app.models.subject import Subject, SubjectGrade
from app.models.track import AcademicTrack, track_subjects, student_custom_subjects
from app.models.course import Course, CourseChapter
from app.models.book import Book, BookChapter
from app.models.plan import StudyPlan, PlanAssignment, PlanStatus, TaskType, CompletionAuditLog, CompletionAuditAction
from app.models.exam import (
    Exam,
    ExamSession,
    ExamTrackConfiguration,
    ExamSubjectConfiguration,
    StudentExamResult,
    StudentExamSubjectResult,
    ExternalExamAssignment,
    ExamReportingGroup,
    ExamReportingGroupSubject,
    HistoricalExamResult,
    HistoricalExamSubjectResult,
    ExamGradeTrackConfig,
    ExamSeriesAssignment,
    ExamSessionAudit,
    StudentExamGroupResult,
)
from app.models.practice_exam import (
    PracticeExam,
    PracticeExamBooklet,
    PracticeExamReportingGroup,
    PracticeExamQuestion,
    PracticeExamAssignment,
    StudentPracticeAttempt,
    StudentPracticeBookletAttempt,
    StudentPracticeAnswer,
)
from app.models.message import (
    Conversation,
    Message,
)

__all__ = [
    "Base",
    "User",
    "UserRole",
    "UserSession",
    "Subject",
    "SubjectGrade",
    "AcademicTrack",
    "track_subjects",
    "student_custom_subjects",
    "Course",
    "CourseChapter",
    "Book",
    "BookChapter",
    "StudyPlan",
    "PlanAssignment",
    "PlanStatus",
    "TaskType",
    "CompletionAuditLog",
    "CompletionAuditAction",
    "Exam",
    "ExamSession",
    "ExamTrackConfiguration",
    "ExamSubjectConfiguration",
    "StudentExamResult",
    "StudentExamSubjectResult",
    "ExternalExamAssignment",
    "ExamReportingGroup",
    "ExamReportingGroupSubject",
    "HistoricalExamResult",
    "HistoricalExamSubjectResult",
    "ExamGradeTrackConfig",
    "ExamSeriesAssignment",
    "ExamSessionAudit",
    "StudentExamGroupResult",
    "PracticeExam",
    "PracticeExamBooklet",
    "PracticeExamReportingGroup",
    "PracticeExamQuestion",
    "PracticeExamAssignment",
    "StudentPracticeAttempt",
    "StudentPracticeBookletAttempt",
    "StudentPracticeAnswer",
    "Conversation",
    "Message",
]
