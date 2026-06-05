from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.case import Case


class CaseRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, skip: int = 0, limit: int = 100) -> List[Case]:
        return self.db.query(Case).offset(skip).limit(limit).all()

    def get(self, case_id: int) -> Optional[Case]:
        return self.db.query(Case).filter(Case.id == case_id).first()

    def get_by_ids(self, case_ids: List[int]) -> List[Case]:
        return self.db.query(Case).filter(Case.id.in_(case_ids)).all()

    def get_case_numbers_by_prefix(self, prefix: str) -> List[str]:
        rows = (
            self.db.query(Case.case_number)
            .filter(Case.case_number.like(f"{prefix}%"))
            .all()
        )
        return [num for (num,) in rows if num]

    def add(self, case: Case) -> Case:
        self.db.add(case)
        self.db.commit()
        self.db.refresh(case)
        return case

    def update(self, case: Case, **kwargs) -> Case:
        for key, value in kwargs.items():
            setattr(case, key, value)
        self.db.commit()
        self.db.refresh(case)
        return case

    def delete(self, case: Case) -> None:
        self.db.delete(case)
        self.db.commit()
