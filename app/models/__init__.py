# app/models/__init__.py
"""
Re-exporta todos los modelos para que cualquier módulo pueda hacer:
    from app.models import Vacancy, Application, Candidate, ...
"""
from app.models.application import Answer, Application  # noqa: F401
from app.models.candidate import Candidate  # noqa: F401
from app.models.cv import AiEvaluation, CvDocument  # noqa: F401
from app.models.question import Question, VacancyQuestion  # noqa: F401
from app.models.scoring_rule import ScoringRule  # noqa: F401
from app.models.session import ConversationSession, SystemLog  # noqa: F401
from app.models.tenant import Tenant  # noqa: F401
from app.models.vacancy import Vacancy  # noqa: F401
