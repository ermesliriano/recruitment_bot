from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import require_admin_token
from app.models.cv_import import CvImportJobItem
from app.schemas.cv_import import CvImportJobOut, CvImportItemOut, ResolvePhoneIn
from app.services.recruiter_cv_intake import ImportedCvFile, RecruiterCvIntakeService

router = APIRouter(
    prefix="/admin/v1/tenants/{tenant_id}/cv-imports",
    tags=["CV imports"],
    dependencies=[Depends(require_admin_token)],
)


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
        return service.retry_outbound(tenant_id=tenant_id, job_id=job_id, item_id=item_id)
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
        return service.resolve_phone(
            tenant_id=tenant_id,
            job_id=job_id,
            item_id=item_id,
            manual_phone=payload.phone,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
