"""Projects & Inspections foundational CRUD endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.inspection import Inspection
from app.models.project import Project
from app.schemas.api import (
    InspectionCreate,
    InspectionResponse,
    ProjectCreate,
    ProjectResponse,
)

router = APIRouter(tags=["projects"])
DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.post("/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    db: DbSession,
) -> Project:
    project = Project(**payload.model_dump())
    db.add(project)
    await db.flush()
    await db.refresh(project)
    return project


@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects(db: DbSession) -> list[Project]:
    result = await db.scalars(select(Project).order_by(Project.created_at.desc()))
    return list(result.all())


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: UUID, db: DbSession) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    return project


@router.post(
    "/inspections",
    response_model=InspectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_inspection(
    payload: InspectionCreate,
    db: DbSession,
) -> Inspection:
    project = await db.get(Project, payload.project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    inspection = Inspection(project_id=payload.project_id, title=payload.title)
    db.add(inspection)
    await db.flush()
    await db.refresh(inspection)
    return inspection


@router.get("/inspections", response_model=list[InspectionResponse])
async def list_inspections(db: DbSession) -> list[Inspection]:
    result = await db.scalars(select(Inspection).order_by(Inspection.created_at.desc()))
    return list(result.all())


@router.get("/inspections/{inspection_id}", response_model=InspectionResponse)
async def get_inspection(inspection_id: UUID, db: DbSession) -> Inspection:
    inspection = await db.get(Inspection, inspection_id)
    if inspection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inspection not found.")
    return inspection
