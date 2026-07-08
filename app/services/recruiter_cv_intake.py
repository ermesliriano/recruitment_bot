from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import phonenumbers
from sqlalchemy import desc, select

from app.channels.email_sendgrid import SendGridEmailGateway, tenant_email_sender
from app.cv_pipeline import extract_cv_text, get_storage, next_cv_version, sha256_bytes, validate_cv
from app.enums import ApplicationOrigin, ApplicationStatus, ChatState, CvParseStatus, Platform
from app.models import Application, Candidate, CvDocument, Tenant, Vacancy
from app.models.cv_import import CvImportJob, CvImportJobItem
from app.services.outbound_message_service import OutboundMessageService
from app.services.phone_extraction import extract_phone_from_text
from app.services.recruitment import RecruitmentService
from app.models.outbound_message import OutboundMessage


EMAIL_REGEX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def extract_email_from_text(text: str | None) -> str | None:
    match = EMAIL_REGEX.search(text or "")
    return match.group(0).lower() if match else None


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
        self.email_gateway = SendGridEmailGateway()

    def create_job(
        self,
        *,
        tenant_id: str,
        vacancy_id: str,
        files: list[ImportedCvFile],
        requested_by: str | None = None,
        scheduled_at: datetime | None = None,
        channel: str = "whatsapp",
    ) -> CvImportJob:
        if channel not in ("whatsapp", "email"):
            raise ValueError(f"Canal de importacion no soportado: {channel}")
        tenant = self.db.execute(
            select(Tenant).where(Tenant.id == tenant_id, Tenant.is_active.is_(True))
        ).scalar_one()

        vacancy = self.db.execute(
            select(Vacancy).where(Vacancy.id == vacancy_id, Vacancy.tenant_id == tenant_id)
        ).scalar_one()

        deferred = scheduled_at is not None

        job = CvImportJob(
            tenant_id=tenant.id,
            vacancy_id=vacancy.id,
            requested_by=requested_by,
            total_files=len(files),
            processed_files=0,
            status="scheduled" if deferred else "processing",
            channel=channel,
            summary_json={"scheduled_at": scheduled_at.isoformat()} if deferred else {},
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
                if deferred:
                    # Modo programado: solo validacion + extraccion de texto +
                    # deteccion de telefono/email. El resto se ejecuta a la hora prevista.
                    self._process_one_file_deferred(item=item, imported_file=imported_file, channel=channel)
                else:
                    self._process_one_file(job=job, item=item, tenant=tenant, vacancy=vacancy, imported_file=imported_file)
            except Exception as exc:
                item.status = "failed"
                item.error_message = str(exc)

            job.processed_files += 1
            items.append(item)
            self.db.flush()

        if not deferred:
            job.status = "completed"
        job.summary_json = self._merge_summary(job, items)
        self.db.commit()
        self.db.refresh(job)
        return job

    def _process_one_file_deferred(self, *, item: CvImportJobItem, imported_file: ImportedCvFile, channel: str = "whatsapp") -> None:
        """Procesado minimo para importaciones programadas: detecta telefono (y email
        si el canal es email) y conserva SIEMPRE el binario para reanudar despues."""
        ext = validate_cv(imported_file.filename, imported_file.mime_type, imported_file.size_bytes)
        extracted_text, parse_status = extract_cv_text(ext, imported_file.content)

        item.extraction_status = parse_status.value if hasattr(parse_status, "value") else str(parse_status)
        item.extracted_preview = (extracted_text or "")[:2000]
        item.raw_content = imported_file.content
        item.detected_email = extract_email_from_text(extracted_text)

        phone_result = extract_phone_from_text(extracted_text)
        item.phone_candidates_json = phone_result.as_dict()
        item.phone_confidence = phone_result.confidence

        if phone_result.status in ("phone_not_found", "ambiguous_phone"):
            item.status = phone_result.status
            item.error_message = phone_result.reason
            return

        item.detected_phone_e164 = phone_result.selected_phone

        if channel == "email" and not item.detected_email:
            item.status = "email_not_found"
            item.error_message = "No se detecto una direccion de email en el CV."
            return

        item.error_message = None
        item.status = "scheduled"

    @staticmethod
    def _job_scheduled_at(job: CvImportJob) -> datetime | None:
        raw = (job.summary_json or {}).get("scheduled_at")
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(str(raw))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _merge_summary(self, job: CvImportJob, items: list[CvImportJobItem]) -> dict[str, Any]:
        """Resumen de estados preservando metadatos del job (scheduled_at)."""
        summary = self._build_summary(items)
        scheduled_at = (job.summary_json or {}).get("scheduled_at")
        if scheduled_at:
            summary["scheduled_at"] = scheduled_at
        return summary

    def run_due_scheduled_jobs(self, *, now: datetime | None = None, force_job_id: str | None = None) -> dict[str, Any]:
        """Ejecuta los jobs programados vencidos (o uno concreto con force_job_id,
        sin esperar a su hora). Los items 'scheduled' con telefono pasan por el
        procesado completo (candidato, candidatura, CV, evaluacion y outbound).
        Los items pendientes de telefono se quedan como estan."""
        now = now or datetime.now(timezone.utc)

        stmt = select(CvImportJob).where(CvImportJob.status == "scheduled")
        if force_job_id:
            stmt = stmt.where(CvImportJob.id == force_job_id)
        jobs = self.db.execute(stmt).scalars().all()

        ran: list[dict[str, Any]] = []
        for job in jobs:
            due_at = self._job_scheduled_at(job)
            if not force_job_id and (due_at is None or due_at > now):
                continue

            tenant = self.db.execute(
                select(Tenant).where(Tenant.id == job.tenant_id, Tenant.is_active.is_(True))
            ).scalar_one_or_none()
            vacancy = self.db.execute(
                select(Vacancy).where(Vacancy.id == job.vacancy_id)
            ).scalar_one_or_none()
            if tenant is None or vacancy is None:
                continue

            items = self.db.execute(
                select(CvImportJobItem).where(
                    CvImportJobItem.job_id == job.id,
                    CvImportJobItem.status == "scheduled",
                )
            ).scalars().all()

            sent = 0
            failed = 0
            for item in items:
                if not item.raw_content or not item.detected_phone_e164:
                    item.status = "failed"
                    item.error_message = "El item programado no conserva CV o telefono para procesarse."
                    failed += 1
                    continue
                try:
                    imported_file = ImportedCvFile(
                        filename=item.original_filename,
                        mime_type=item.mime_type or "application/octet-stream",
                        content=bytes(item.raw_content),
                    )
                    ext = validate_cv(imported_file.filename, imported_file.mime_type, imported_file.size_bytes)
                    extracted_text, parse_status = extract_cv_text(ext, imported_file.content)
                    self._continue_processing(
                        job=job,
                        item=item,
                        tenant=tenant,
                        vacancy=vacancy,
                        imported_file=imported_file,
                        ext=ext,
                        extracted_text=extracted_text,
                        parse_status=parse_status,
                        phone_e164=item.detected_phone_e164,
                    )
                    sent += 1
                except Exception as exc:
                    self.db.rollback()
                    item.status = "failed"
                    item.error_message = str(exc)
                    failed += 1
                    self.db.commit()

            # El job termina: los items pendientes de telefono siguen visibles
            # para corregirse; al resolverse (job ya no 'scheduled'), se envian
            # inmediatamente por el flujo habitual.
            job.status = "completed"
            job.completed_at = now
            job.summary_json = self._refresh_job_summary(str(job.id), job=job)
            self.db.commit()
            ran.append({"job_id": str(job.id), "sent": sent, "failed": failed})

        return {"executed_jobs": ran, "count": len(ran)}

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

    def resolve_phone(self, *, tenant_id: str, job_id: str, item_id: str, manual_phone: str) -> CvImportJobItem:
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

        if item.status not in ("phone_not_found", "ambiguous_phone"):
            raise ValueError("El ítem no está pendiente por teléfono no detectado.")

        if not item.raw_content:
            raise ValueError(
                "No se conserva el contenido del CV para reprocesar este ítem; vuelve a subir el fichero."
            )

        phone_e164 = self._normalize_manual_phone(manual_phone)

        job = self.db.execute(
            select(CvImportJob).where(CvImportJob.id == job_id, CvImportJob.tenant_id == tenant_id)
        ).scalar_one()

        # Job programado y aun no vencido: el telefono queda registrado y el CV
        # vuelve a la cola programada (se procesara con el resto a la hora prevista),
        # sin enviar ningun mensaje ahora.
        if job.status == "scheduled":
            item.detected_phone_e164 = phone_e164
            item.error_message = None
            item.status = "scheduled"
            item.phone_confidence = Decimal("1.00")
            item.phone_candidates_json = {
                "selected_phone": phone_e164,
                "confidence": 1.0,
                "status": "manual",
                "reason": "Teléfono introducido manualmente por el reclutador.",
                "candidates": [],
            }
            job.summary_json = self._refresh_job_summary(job_id, job=job)
            self.db.commit()
            self.db.refresh(item)
            return item

        vacancy = self.db.execute(
            select(Vacancy).where(Vacancy.id == job.vacancy_id, Vacancy.tenant_id == tenant_id)
        ).scalar_one()

        imported_file = ImportedCvFile(
            filename=item.original_filename,
            mime_type=item.mime_type or "application/octet-stream",
            content=bytes(item.raw_content),
        )

        ext = validate_cv(imported_file.filename, imported_file.mime_type, imported_file.size_bytes)
        extracted_text, parse_status = extract_cv_text(ext, imported_file.content)

        item.extraction_status = parse_status.value if hasattr(parse_status, "value") else str(parse_status)
        item.extracted_preview = (extracted_text or "")[:2000]
        item.phone_confidence = Decimal("1.00")
        item.phone_candidates_json = {
            "selected_phone": phone_e164,
            "confidence": 1.0,
            "status": "manual",
            "reason": "Teléfono introducido manualmente por el reclutador.",
            "candidates": [],
        }

        self._continue_processing(
            job=job,
            item=item,
            tenant=tenant,
            vacancy=vacancy,
            imported_file=imported_file,
            ext=ext,
            extracted_text=extracted_text,
            parse_status=parse_status,
            phone_e164=phone_e164,
        )

        job.summary_json = self._refresh_job_summary(job_id, job=job)
        self.db.commit()
        self.db.refresh(item)
        return item

    def _refresh_job_summary(self, job_id: str, job: CvImportJob | None = None) -> dict[str, Any]:
        items = self.db.execute(
            select(CvImportJobItem).where(CvImportJobItem.job_id == job_id)
        ).scalars().all()
        if job is None:
            job = self.db.execute(
                select(CvImportJob).where(CvImportJob.id == job_id)
            ).scalar_one()
        return self._merge_summary(job, items)

    @staticmethod
    def _normalize_manual_phone(raw: str) -> str:
        value = (raw or "").strip()
        if not value:
            raise ValueError("Debes indicar un número de teléfono.")
        try:
            parsed = phonenumbers.parse(value, "ES")
        except phonenumbers.NumberParseException:
            raise ValueError("El número de teléfono no es válido.")
        if not phonenumbers.is_valid_number(parsed):
            raise ValueError("El número de teléfono no es válido.")
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)

    def _process_one_file(self, *, job: CvImportJob, item: CvImportJobItem, tenant, vacancy, imported_file: ImportedCvFile) -> None:
        ext = validate_cv(imported_file.filename, imported_file.mime_type, imported_file.size_bytes)
        extracted_text, parse_status = extract_cv_text(ext, imported_file.content)

        item.extraction_status = parse_status.value if hasattr(parse_status, "value") else str(parse_status)
        item.extracted_preview = (extracted_text or "")[:2000]
        item.detected_email = extract_email_from_text(extracted_text)

        phone_result = extract_phone_from_text(extracted_text)
        item.phone_candidates_json = phone_result.as_dict()
        item.phone_confidence = phone_result.confidence

        if phone_result.status in ("phone_not_found", "ambiguous_phone"):
            item.status = phone_result.status
            item.error_message = phone_result.reason
            # Conservamos el binario original del CV para poder reanudar el
            # procesado cuando el reclutador introduzca el teléfono manualmente.
            item.raw_content = imported_file.content
            return

        if (job.channel or "whatsapp") == "email" and not item.detected_email:
            item.status = "email_not_found"
            item.error_message = "No se detecto una direccion de email en el CV."
            item.detected_phone_e164 = phone_result.selected_phone
            item.raw_content = imported_file.content
            return

        phone_e164 = phone_result.selected_phone
        self._continue_processing(
            job=job,
            item=item,
            tenant=tenant,
            vacancy=vacancy,
            imported_file=imported_file,
            ext=ext,
            extracted_text=extracted_text,
            parse_status=parse_status,
            phone_e164=phone_e164,
        )

    def _continue_processing(
        self,
        *,
        job: CvImportJob,
        item: CvImportJobItem,
        tenant,
        vacancy,
        imported_file: ImportedCvFile,
        ext: str,
        extracted_text: str,
        parse_status,
        phone_e164: str,
    ) -> None:
        item.detected_phone_e164 = phone_e164
        item.error_message = None
        # Una vez reanudado el procesado ya no necesitamos conservar el binario.
        item.raw_content = None

        candidate, candidate_reused = self._get_or_create_candidate(tenant_id=str(tenant.id), phone_e164=phone_e164)
        application, application_reused = self._get_or_reuse_application(
            tenant_id=str(tenant.id),
            candidate_id=str(candidate.id),
            vacancy_id=str(vacancy.id),
        )

        application.origin = ApplicationOrigin.RECRUITER_UPLOAD
        job_channel = (job.channel or "whatsapp")
        channel_platform = Platform.EMAIL if job_channel == "email" else Platform.WHATSAPP
        application.preferred_platform = channel_platform
        if job_channel == "email" and item.detected_email:
            candidate.email = candidate.email or item.detected_email

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
            source_platform=channel_platform,
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
            platform=channel_platform,
            email=(item.detected_email or candidate.email) if job_channel == "email" else None,
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

        # ── Canal EMAIL: outbound con preguntas agrupadas en un solo correo ────
        if job_channel == "email":
            to_email = item.detected_email or candidate.email
            try:
                record_status = self._send_outbound_email(
                    tenant=tenant,
                    candidate=candidate,
                    application=application,
                    session=session,
                    vacancy=vacancy,
                    to_email=to_email,
                    include_questions=pending_questions > 0,
                )
                item.outbound_status = record_status
                if pending_questions == 0 and application.status in {
                    ApplicationStatus.REVIEW,
                    ApplicationStatus.INTERVIEW,
                    ApplicationStatus.SHORTLIST,
                    ApplicationStatus.REJECTED,
                }:
                    item.status = "scoring_completed"
                else:
                    application.status = ApplicationStatus.WAITING_CANDIDATE_REPLY
                    session.current_state = ChatState.WAITING_CANDIDATE_REPLY
                    item.status = "waiting_reply"
            except Exception as exc:
                item.outbound_status = "failed"
                item.status = "failed"
                item.error_message = f"Error enviando email: {exc}"
            self.db.commit()
            return

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

    def _send_outbound_email(
        self,
        *,
        tenant,
        candidate,
        application,
        session,
        vacancy,
        to_email: str | None,
        include_questions: bool,
    ) -> str:
        """Envia el correo outbound (con las preguntas de la vacante agrupadas si
        procede) y registra el OutboundMessage. Devuelve el status registrado."""
        if not to_email:
            raise ValueError("El candidato no tiene direccion de email.")

        from_email, from_name, reply_to = tenant_email_sender(tenant)

        greeting_name = (candidate.full_name or "").strip()
        greeting = f"Hola {greeting_name}," if greeting_name else "Hola,"

        lines: list[str] = [
            greeting,
            "",
            f"Hemos recibido tu CV para la vacante \"{vacancy.title}\" de {tenant.name} "
            "y nos gustaria continuar con tu candidatura.",
        ]

        questions_block: list[str] = []
        if include_questions:
            ordered = self.recruitment._get_ordered_questions(self.db, str(vacancy.id))
            for idx, (vq, q) in enumerate(ordered, start=1):
                prompt = vq.prompt_override or q.prompt_text
                questions_block.append(f"{idx}. {prompt}")

        if questions_block:
            lines += [
                "",
                "Para completar tu postulacion, por favor responde a este correo "
                "contestando a las siguientes preguntas (puedes responderlas en el "
                "mismo orden, numeradas):",
                "",
                *questions_block,
            ]
        else:
            lines += [
                "",
                "Tu candidatura ha quedado registrada. El equipo de Recursos Humanos "
                "revisara tu perfil y te contactara con los siguientes pasos.",
            ]

        lines += [
            "",
            "Gracias por tu interes.",
            f"{tenant.name} - Equipo de Reclutamiento",
        ]
        text_body = "\n".join(lines)
        subject = f"Tu candidatura para {vacancy.title} - {tenant.name}"

        record = OutboundMessage(
            tenant_id=tenant.id,
            candidate_id=candidate.id,
            application_id=application.id,
            conversation_session_id=session.id if session is not None else None,
            channel=Platform.EMAIL,
            provider="sendgrid",
            to_address=to_email,
            template_sid=None,
            content_text=text_body,
            content_variables={"subject": subject},
            status="queued",
        )
        self.db.add(record)
        self.db.flush()

        try:
            result = self.email_gateway.send_email(
                to_email=to_email,
                subject=subject,
                text_body=text_body,
                from_email=from_email,
                from_name=from_name,
                reply_to=reply_to,
            )
            record.status = "sent"
            record.sent_at = datetime.now(timezone.utc)
            record.provider_message_sid = result.get("message_id")
        except Exception as exc:
            record.status = "failed"
            record.error_message = str(exc)[:2000]
            raise
        finally:
            self.db.flush()

        return record.status

    def resolve_email(self, *, tenant_id: str, job_id: str, item_id: str, manual_email: str) -> CvImportJobItem:
        """Resuelve manualmente el email de un item 'email_not_found' y reanuda el
        procesado (o lo devuelve a la cola programada si el job esta programado)."""
        item = self.db.execute(
            select(CvImportJobItem).where(
                CvImportJobItem.id == item_id,
                CvImportJobItem.job_id == job_id,
                CvImportJobItem.tenant_id == tenant_id,
            )
        ).scalar_one()

        if item.status != "email_not_found":
            raise ValueError("El item no esta pendiente por email no detectado.")
        if not item.raw_content:
            raise ValueError(
                "No se conserva el contenido del CV para reprocesar este item; vuelve a subir el fichero."
            )

        email = (manual_email or "").strip().lower()
        if not EMAIL_REGEX.fullmatch(email):
            raise ValueError("La direccion de email no es valida.")

        job = self.db.execute(
            select(CvImportJob).where(CvImportJob.id == job_id, CvImportJob.tenant_id == tenant_id)
        ).scalar_one()

        item.detected_email = email
        item.error_message = None

        if job.status == "scheduled":
            item.status = "scheduled"
            job.summary_json = self._refresh_job_summary(job_id, job=job)
            self.db.commit()
            self.db.refresh(item)
            return item

        vacancy = self.db.execute(
            select(Vacancy).where(Vacancy.id == job.vacancy_id, Vacancy.tenant_id == tenant_id)
        ).scalar_one()
        tenant = self.db.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        ).scalar_one()

        imported_file = ImportedCvFile(
            filename=item.original_filename,
            mime_type=item.mime_type or "application/octet-stream",
            content=bytes(item.raw_content),
        )
        ext = validate_cv(imported_file.filename, imported_file.mime_type, imported_file.size_bytes)
        extracted_text, parse_status = extract_cv_text(ext, imported_file.content)

        self._continue_processing(
            job=job,
            item=item,
            tenant=tenant,
            vacancy=vacancy,
            imported_file=imported_file,
            ext=ext,
            extracted_text=extracted_text,
            parse_status=parse_status,
            phone_e164=item.detected_phone_e164,
        )

        job.summary_json = self._refresh_job_summary(job_id, job=job)
        self.db.commit()
        self.db.refresh(item)
        return item

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
