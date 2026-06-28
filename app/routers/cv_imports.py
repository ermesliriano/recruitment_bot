from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import require_admin_token
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.cv_import import CvImportJobItem
from app.schemas.cv_import import CvImportJobOut, CvImportItemOut, ResolvePhoneIn
from app.services.recruiter_cv_intake import ImportedCvFile, RecruiterCvIntakeService

router = APIRouter(
    prefix="/admin/v1/tenants/{tenant_id}/cv-imports",
    tags=["CV imports"],
    dependencies=[Depends(require_admin_token)],
)


def _attach_candidate_names(db: Session, items) -> None:
    """Enriquece cada item (atributos transitorios) con:

    - candidate_full_name: nombre del candidato.
    - effective_status: estado a MOSTRAR, derivado del estado REAL de la
      candidatura. item.status se congela en 'waiting_reply' cuando sale el
      outbound y nadie lo avanza; aqui, si la candidatura ya esta evaluada
      (score_total no nulo), mostramos 'scoring_completed'.
    """
    candidate_ids = {item.candidate_id for item in items if item.candidate_id}
    names: dict = {}
    if candidate_ids:
        rows = db.execute(
            select(Candidate.id, Candidate.full_name).where(
                Candidate.id.in_(candidate_ids)
            )
        ).all()
        names = {cid: full_name for cid, full_name in rows}

    application_ids = {item.application_id for item in items if item.application_id}
    score_by_app: dict = {}
    if application_ids:
        rows = db.execute(
            select(Application.id, Application.score_total).where(
                Application.id.in_(application_ids)
            )
        ).all()
        score_by_app = {app_id: score_total for app_id, score_total in rows}

    # Estados que indican que el outbound ya salio y se espera al candidato.
    sent_statuses = {"waiting_reply", "scoring_completed", "template_sent"}

    for item in items:
        item.candidate_full_name = names.get(item.candidate_id)

        evaluated = (
            item.application_id is not None
            and score_by_app.get(item.application_id) is not None
        )
        if evaluated:
            item.effective_status = "scoring_completed"
        elif str(item.status or "") in sent_statuses:
            # Outbound enviado pero la candidatura aun no se ha evaluado.
            item.effective_status = "waiting_reply"
        else:
            # Estados de fallo/bloqueo/telefono: se respetan tal cual.
            item.effective_status = item.status


def _serialize_job(job) -> dict:
    return {
        "id": job.id,
        "tenant_id": job.tenant_id,
        "vacancy_id": job.vacancy_id,
        "requested_by": job.requested_by,
        "total_files": job.total_files,
        "processed_files": job.processed_files,
        "status": job.status,
        "summary_json": job.summary_json or {},
        "items": list(getattr(job, "items", []) or []),
    }


@router.post("", response_model=CvImportJobOut)
async def create_cv_import_job(
    tenant_id: str,
    vacancy_id: str = Form(...),
    requested_by: str | None = Form(default=None),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    imported_files: list[ImportedCvFile] = []
    for file in files:
        imported_files.append(
            ImportedCvFile(
                filename=file.filename or "cv.bin",
                mime_type=file.content_type or "application/octet-stream",
                content=await file.read(),
            )
        )

    service = RecruiterCvIntakeService(db)
    job = service.create_job(
        tenant_id=tenant_id,
        vacancy_id=vacancy_id,
        files=imported_files,
        requested_by=requested_by,
    )
    db.refresh(job)
    job.items = db.execute(
        select(CvImportJobItem).where(CvImportJobItem.job_id == job.id)
    ).scalars().all()
    _attach_candidate_names(db, job.items)
    return _serialize_job(job)


@router.get("", response_model=list[CvImportJobOut])
def list_cv_import_jobs(
    tenant_id: str,
    vacancy_id: str | None = None,
    db: Session = Depends(get_db),
):
    service = RecruiterCvIntakeService(db)
    jobs = service.list_jobs(tenant_id=tenant_id, vacancy_id=vacancy_id)
    for job in jobs:
        job.items = db.execute(
            select(CvImportJobItem).where(CvImportJobItem.job_id == job.id)
        ).scalars().all()
        _attach_candidate_names(db, job.items)
    return [_serialize_job(job) for job in jobs]


@router.get("/{job_id}", response_model=CvImportJobOut)
def get_cv_import_job(
    tenant_id: str,
    job_id: str,
    db: Session = Depends(get_db),
):
    service = RecruiterCvIntakeService(db)
    job = service.get_job(tenant_id=tenant_id, job_id=job_id)
    job.items = db.execute(
        select(CvImportJobItem).where(CvImportJobItem.job_id == job.id)
    ).scalars().all()
    _attach_candidate_names(db, job.items)
    return _serialize_job(job)


@router.post("/{job_id}/items/{item_id}/retry-outbound", response_model=CvImportItemOut)
def retry_outbound_message(
    tenant_id: str,
    job_id: str,
    item_id: str,
    db: Session = Depends(get_db),
):
    service = RecruiterCvIntakeService(db)
    try:
        item = service.retry_outbound(tenant_id=tenant_id, job_id=job_id, item_id=item_id)
        _attach_candidate_names(db, [item])
        return item
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/{job_id}/items/{item_id}/resolve-phone", response_model=CvImportItemOut)
def resolve_phone(
    tenant_id: str,
    job_id: str,
    item_id: str,
    payload: ResolvePhoneIn,
    db: Session = Depends(get_db),
):
    service = RecruiterCvIntakeService(db)
    try:
        item = service.resolve_phone(
            tenant_id=tenant_id,
            job_id=job_id,
            item_id=item_id,
            manual_phone=payload.phone,
        )
        _attach_candidate_names(db, [item])
        return item
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
