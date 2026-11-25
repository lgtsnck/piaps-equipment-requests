import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from equipment_requests.domain.enums import RequestStatus
from equipment_requests.domain.models import EquipmentRequest

from .base import RequestRepository


class SQLiteRequestRepository(RequestRepository):
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        if str(self._db_path) == ":memory:":
            raise ValueError("Для SQLiteRequestRepository необходим путь к файлу базы данных")
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    applicant_id INTEGER NOT NULL CHECK (applicant_id > 0),
                    department_id INTEGER NOT NULL CHECK (department_id > 0),
                    equipment_id INTEGER NOT NULL CHECK (equipment_id > 0),
                    quantity INTEGER NOT NULL CHECK (quantity > 0),
                    justification TEXT NOT NULL CHECK (length(trim(justification)) > 0),
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    assigned_specialist_id INTEGER
                        CHECK (assigned_specialist_id IS NULL OR assigned_specialist_id > 0),
                    decision_reason TEXT,
                    completion_result TEXT
                )
                """
            )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self._db_path)) as connection:
            connection.row_factory = sqlite3.Row
            with connection:
                yield connection

    @staticmethod
    def _values(request: EquipmentRequest) -> tuple[object, ...]:
        return (
            request.applicant_id,
            request.department_id,
            request.equipment_id,
            request.quantity,
            request.justification,
            request.created_at.isoformat(),
            request.status.value,
            request.assigned_specialist_id,
            request.decision_reason,
            request.completion_result,
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> EquipmentRequest:
        return EquipmentRequest(
            id=row["id"],
            applicant_id=row["applicant_id"],
            department_id=row["department_id"],
            equipment_id=row["equipment_id"],
            quantity=row["quantity"],
            justification=row["justification"],
            created_at=datetime.fromisoformat(row["created_at"]),
            status=RequestStatus(row["status"]),
            assigned_specialist_id=row["assigned_specialist_id"],
            decision_reason=row["decision_reason"],
            completion_result=row["completion_result"],
        )

    def add(self, request: EquipmentRequest) -> None:
        if request.id != 0:
            raise ValueError("Добавить можно только новую заявку без идентификатора")

        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO requests (
                    applicant_id, department_id, equipment_id, quantity,
                    justification, created_at, status, assigned_specialist_id,
                    decision_reason, completion_result
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._values(request),
            )
            new_id = cursor.lastrowid

        request.id = int(new_id)

    def get_by_id(self, id: int) -> EquipmentRequest:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM requests WHERE id = ?", (id,)
            ).fetchone()

        if row is None:
            raise KeyError(f"Заявка с идентификатором {id} не найдена")
        return self._from_row(row)

    def list_all(self) -> list[EquipmentRequest]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM requests ORDER BY id"
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def save(self, request: EquipmentRequest) -> None:
        if request.id <= 0:
            raise ValueError("Перед обновлением заявку необходимо сохранить через add()")

        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE requests SET
                    applicant_id = ?,
                    department_id = ?,
                    equipment_id = ?,
                    quantity = ?,
                    justification = ?,
                    created_at = ?,
                    status = ?,
                    assigned_specialist_id = ?,
                    decision_reason = ?,
                    completion_result = ?
                WHERE id = ?
                """,
                (*self._values(request), request.id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Заявка с идентификатором {request.id} не найдена")
