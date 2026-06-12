from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import desc, select

from app.cv_pipeline import extract_cv_text, get_storage, next_cv_version, sha256_bytes, validate_cv
from app.enums import ApplicationOrigin, ApplicationStatus, ChatState, CvParseStatus, Platform
from app.models import Application, Candidate, CvDocument, Tenant, Vacancy
from app.models.cv_import import CvImportJob, CvImportJobItem
from app.services.outbound_message_service import OutboundMessageService
from app.services.phone_extraction import extract_phone_from_text
from app.services.recruitment import RecruitmentService


OPEN_APPLICATION_STATUSES = {
    ApplicationStatus.DRAFT,
    ApplicationStatus.IN_PROGRESS,
    ApplicationStatus.PENDING_AI,
    ApplicationStatus.SCORING,
    ApplicationStatus.WAITING_CANDIDATE_REPLY,
    ApplicationStatus.NEEDS_HUMAN,
    ApplicationStatus.BLOCKED_NO_OPT_IN,
}


@dataclass(slots=True)
class ImportedCvFile:
    filename: str
    mime_type: str
    content: bytes

    @property
    def size_bytes(self) -> int:
        return len(self.content)


class RecruiterCvIntakeService:
    def __init__(self, db) -> None:
        self.db = db
        self.recruitment = RecruitmentService()
        self.outbound = OutboundMessageService()

    def create_job(
        self,
        *,
        tenant_id: str,
        vacancy_id: str,
        files: list[ImportedCvFile],
        requested_by: str | None = None,
    ) -> CvImportJob:
        tenant = self.db.execute(
            select(Tenant).where(Tenant.id == tenant_id, Tenant.is_active.is_(True))
        ).scalar_one()

        vacancy = self.db.execute(
            select(Vacancy).where(Vacancy.id == vacancy_id, Vacancy.tenant_id == tenant_id)
        ).scalar_one()

        job = CvImportJob(
            tenant_id=tenant.id,
            vacancy_id=vacancy.id,
            requested_by=requested_by,
            total_files=len(files),
            processed_files=0,
            status="processing",
            summary_json={},
        )
        self.db.add(job)
        self.db.flush()

        items: list[CvImportJobItem] = []

        for imported_file in files:
            item = CvImportJobItem(
                job_id=job.id,
                tenant_id=tenant.id,
                original_filename=imported_file.filename,
                mime_type=imported_file.mime_type,
                size_bytes=imported_file.size_bytes,
                status="processing",
                outbound_status=None,
            )
            self.db.add(item)
            self.db.flush()

            try:
                self._process_one_file(job=job, item=item, tenant=tenant, vacancy=vacancy, imported_file=imported_file)
            except Exception as exc:
                item.status = "failed"
                item.error_message = str(exc)

            job.processed_files += 1
            items.append(item)
            self.db.flush()

        job.status = "completed"
        job.summary_json = self._build_summary(items)
        self.db.commit()
        self.db.refresh(job)
        return job

    def get_job(self, tenant_id: str, job_id: str) -> CvImportJob:
        return self.db.execute(
            select(CvImportJob).where(CvImportJob.id == job_id, CvImportJob.tenant_id == tenant_id)
        ).scalar_one()

    def list_jobs(self, tenant_id: str, vacancy_id: str | None = None) -> list[CvImportJob]:
        stmt = select(CvImportJob).where(CvImportJob.tenant_id == tenant_id).order_by(desc(CvImportJob.created_at))
        if vacancy_id:
            stmt = stmt.where(CvImportJob.vacancy_id == vacancy_id)
        return self.db.execute(stmt).scalars().all()

    def retry_outbound(self, *, tenant_id: str, job_id: str, item_id: str) -> CvImportJobItem:
        tenant = self.db.execute(
            select(Tenant).where(Tenant.id == tenant_id, Tenant.is_active.is_(True))
        ).scalar_one()

        item = self.db.execute(
            select(CvImportJobItem).where(
                CvImportJobItem.id == item_id,
                CvImportJobItem.job_id == job_id,
                CvImportJobItem.tenant_id == tenant_id,
            )
        ).scalar_one()

        if not item.application_id or not item.detected_phone_e164:
            raise ValueError("El ítem no tiene application o teléfono válidos para reintentar outbound.")

        application = self.db.execute(select(Application).where(Application.id == item.application_id)).scalar_one()
        candidate = self.db.execute(select(Candidate).where(Candidate.id == application.candidate_id)).scalar_one()
        vacancy = self.db.execute(select(Vacancy).where(Vacancy.id == application.vacancy_id)).scalar_one()
        session = self.recruitment.get_or_create_seeded_session(
            self.db,
            tenant_id=str(tenant.id),
            candidate_id=str(candidate.id),
            application_id=str(application.id),
            phone_e164=candidate.phone_e164,
            vacancy_id=str(vacancy.id),
        )

        record = self.outbound.send_seeded_template(
            self.db,
            tenant,
            candidate_id=candidate.id,
            application_id=application.id,
            conversation_session_id=session.id,
            to_phone_e164=candidate.phone_e164,
            candidate_name=candidate.full_name,
            vacancy_title=vacancy.title,
        )

        item.outbound_status = record.status
        item.status = "waiting_reply"
        self.db.commit()
        self.db.refresh(item)
        return item

    def _process_one_file(self, *, job: CvImportJob, item: CvImportJobItem, tenant, vacancy, imported_file: ImportedCvFile) -> None:
        ext = validate_cv(imported_file.filename, imported_file.mime_type, imported_file.size_bytes)
        extracted_text, parse_status = extract_cv_text(ext, imported_file.content)

        item.extraction_status = parse_status.value if hasattr(parse_status, "value") else str(parse_status)
        item.extracted_preview = (extracted_text or "")[:2000]

        phone_result = extract_phone_from_text(extracted_text)
        item.phone_candidates_json = phone_result.as_dict()
        item.phone_confidence = phone_result.confidence

        if phone_result.status == "phone_not_found":
            item.status = "phone_not_found"
            item.error_message = phone_result.reason
            return

        if phone_result.status == "ambiguous_phone":
            item.status = "ambiguous_phone"
            item.error_message = phone_result.reason
            return

        phone_e164 = phone_result.selected_phone
        item.detected_phone_e164 = phone_e164

        candidate, candidate_reused = self._get_or_create_candidate(tenant_id=str(tenant.id), phone_e164=phone_e164)
        application, application_reused = self._get_or_reuse_application(
            tenant_id=str(tenant.id),
            candidate_id=str(candidate.id),
            vacancy_id=str(vacancy.id),
        )

        application.origin = ApplicationOrigin.RECRUITER_UPLOAD
        application.preferred_platform = Platform.WHATSAPP

        version = next_cv_version(self.db, application.id)
        storage, backend_enum = get_storage()
        storage_key, content_blob = storage.save(tenant.id, application.id, version, imported_file.filename, imported_file.content)

        cv_document = CvDocument(
            tenant_id=tenant.id,
            application_id=application.id,
            version=version,
            original_filename=imported_file.filename,
            mime_type=imported_file.mime_type,
            extension=ext,
            size_bytes=imported_file.size_bytes,
            sha256=sha256_bytes(imported_file.content),
            source_platform=Platform.WHATSAPP,
            source_file_id=None,
            source_file_unique_id=None,
            source_metadata_json={
                "source": "recruiter_upload",
                "cv_import_job_id": str(job.id),
                "cv_import_job_item_id": str(item.id),
            },
            storage_backend=backend_enum,
            storage_key=storage_key,
            content=content_blob,
            extracted_text=extracted_text,
            parse_status=parse_status if isinstance(parse_status, CvParseStatus) else CvParseStatus.PENDING,
        )
        self.db.add(cv_document)
        self.db.flush()

        session = self.recruitment.get_or_create_seeded_session(
            self.db,
            tenant_id=str(tenant.id),
            candidate_id=str(candidate.id),
            application_id=str(application.id),
            phone_e164=phone_e164,
            vacancy_id=str(vacancy.id),
        )

        application.status = ApplicationStatus.PENDING_AI
        self.db.flush()
        self.db.commit()

        self.recruitment.run_cv_pipeline_async(
            tenant_id=str(tenant.id),
            application_id=str(application.id),
            cv_document_id=str(cv_document.id),
            dispatch_messages=False,
        )

        self.db.expire_all()

        application = self.db.execute(select(Application).where(Application.id == application.id)).scalar_one()
        session = self.db.execute(select(type(session)).where(type(session).id == session.id)).scalar_one()
        candidate = self.db.execute(select(Candidate).where(Candidate.id == candidate.id)).scalar_one()

        item.candidate_id = candidate.id
        item.application_id = application.id
        item.candidate_reused = candidate_reused
        item.application_reused = application_reused

        pending_questions = self.recruitment.count_pending_vacancy_questions(self.db, str(application.id))

        if pending_questions == 0 and application.status in {
            ApplicationStatus.REVIEW,
            ApplicationStatus.INTERVIEW,
            ApplicationStatus.SHORTLIST,
            ApplicationStatus.REJECTED,
        }:
            sent = self._try_send_seeded_template(
                tenant=tenant,
                candidate=candidate,
                application=application,
                session=session,
                vacancy_title=vacancy.title,
            )
            item.outbound_status = "template_sent" if sent else None
            item.status = "scoring_completed"
            return

        if not self._can_send_outbound(tenant=tenant, candidate=candidate):
            application.status = ApplicationStatus.BLOCKED_NO_OPT_IN
            session.current_state = ChatState.WAITING_CANDIDATE_REPLY
            item.status = "blocked_no_opt_in"
            self.db.commit()
            return

        record = self.outbound.send_seeded_template(
            self.db,
            tenant,
            candidate_id=candidate.id,
            application_id=application.id,
            conversation_session_id=session.id,
            to_phone_e164=candidate.phone_e164,
            candidate_name=candidate.full_name,
            vacancy_title=vacancy.title,
        )
        application.status = ApplicationStatus.WAITING_CANDIDATE_REPLY
        session.current_state = ChatState.WAITING_CANDIDATE_REPLY
        item.outbound_status = record.status
        item.status = "waiting_reply"
        self.db.commit()

    def _try_send_seeded_template(self, *, tenant, candidate, application, session, vacancy_title: str) -> bool:
        if not self._can_send_outbound(tenant=tenant, candidate=candidate):
            return False

        self.outbound.send_seeded_template(
            self.db,
            tenant,
            candidate_id=candidate.id,
            application_id=application.id,
            conversation_session_id=session.id,
            to_phone_e164=candidate.phone_e164,
            candidate_name=candidate.full_name,
            vacancy_title=vacancy_title,
        )
        self.db.commit()
        return True

    def _can_send_outbound(self, *, tenant, candidate) -> bool:
        if candidate.whatsapp_opt_in_status == "granted":
            return True
        if tenant.whatsapp_assume_opt_in:
            candidate.whatsapp_opt_in_status = "granted"
            return True
        return False

    def _get_or_create_candidate(self, *, tenant_id: str, phone_e164: str) -> tuple[Candidate, bool]:
        candidate = self.db.execute(
            select(Candidate).where(Candidate.tenant_id == tenant_id, Candidate.phone_e164 == phone_e164)
        ).scalar_one_or_none()

        if candidate:
            return candidate, True

        candidate = Candidate(
            tenant_id=tenant_id,
            phone_e164=phone_e164,
            whatsapp_opt_in_status="unknown",
        )
        self.db.add(candidate)
        self.db.flush()
        return candidate, False

    def _get_or_reuse_application(self, *, tenant_id: str, candidate_id: str, vacancy_id: str) -> tuple[Application, bool]:
        # Un candidato no puede tener más de una candidatura para la misma vacante:
        # reutilizamos cualquier candidatura existente (independientemente del estado).
        application = self.db.execute(
            select(Application)
            .where(
                Application.tenant_id == tenant_id,
                Application.candidate_id == candidate_id,
                Application.vacancy_id == vacancy_id,
            )
            .order_by(desc(Application.updated_at))
        ).scalars().first()

        if application:
            return application, True

        application = Application(
            tenant_id=tenant_id,
            candidate_id=candidate_id,
            vacancy_id=vacancy_id,
            status=ApplicationStatus.DRAFT,
            origin=ApplicationOrigin.RECRUITER_UPLOAD,
            preferred_platform=Platform.WHATSAPP,
        )
        self.db.add(application)
        self.db.flush()
        return application, False

    @staticmethod
    def _build_summary(items: list[CvImportJobItem]) -> dict[str, Any]:
        summary: dict[str, int] = {}
        for item in items:
            summary[item.status] = summary.get(item.status, 0) + 1
        return summary
