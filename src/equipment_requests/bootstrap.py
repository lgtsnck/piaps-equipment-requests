from pathlib import Path

from equipment_requests.data.reference_data import EQUIPMENT, USERS
from equipment_requests.repositories.base import RequestRepository
from equipment_requests.repositories.sqlite_repository import SQLiteRequestRepository
from equipment_requests.services.request_service import RequestService


def create_repository(db_path: str | Path = "requests.db") -> RequestRepository:
    return SQLiteRequestRepository(db_path)


def create_service(repository: RequestRepository, user_id: int) -> RequestService:
    if type(user_id) is not int or user_id <= 0:
        raise ValueError("Необходимо указать корректный идентификатор пользователя")

    current_user = next((user for user in USERS if user.id == user_id), None)
    if current_user is None:
        raise ValueError(f"Пользователь с идентификатором {user_id} не найден")

    return RequestService(
        repository=repository,
        current_user=current_user,
        users=USERS,
        equipment=EQUIPMENT,
    )
