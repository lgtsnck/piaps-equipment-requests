from collections.abc import Iterable

from equipment_requests.domain.enums import RequestStatus, UserRole
from equipment_requests.domain.models import Equipment, EquipmentRequest, User
from equipment_requests.repositories.base import RequestRepository


class RequestService:
    def __init__(
        self,
        repository: RequestRepository,
        current_user: User,
        users: Iterable[User],
        equipment: Iterable[Equipment],
    ) -> None:
        self._repository = repository
        self._users = {user.id: user for user in users}
        self._equipment = {item.id: item for item in equipment}

        registered_user = self._users.get(current_user.id)
        if registered_user is None or registered_user != current_user:
            raise ValueError("Текущий пользователь отсутствует в справочнике пользователей")
        self._current_user = registered_user

    def _require_role(self, role: UserRole) -> None:
        if not self._current_user.has_role(role):
            raise PermissionError("У текущего пользователя нет прав для выполнения операции")

    def _require_owner(self, request: EquipmentRequest) -> None:
        if request.applicant_id != self._current_user.id:
            raise PermissionError("Изменять и отправлять можно только собственные заявки")

    def _can_view(self, request: EquipmentRequest) -> bool:
        if self._current_user.role in (UserRole.MANAGER, UserRole.SPECIALIST):
            return True
        return request.department_id == self._current_user.department_id

    @staticmethod
    def _require_text(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Необходимо указать {field_name}")
        return value.strip()

    def _get_request(self, id: int) -> EquipmentRequest:
        if type(id) is not int or id <= 0:
            raise ValueError("id заявки должен быть положительным целым числом")
        return self._repository.get_by_id(id)

    @staticmethod
    def _validate_filter_id(value: int | None, field_name: str) -> None:
        if value is not None and (type(value) is not int or value <= 0):
            raise ValueError(f"{field_name} должен быть положительным целым числом")

    def create_request(
        self,
        applicant_id: int,
        equipment_id: int,
        quantity: int,
        justification: str,
    ) -> EquipmentRequest:
        if type(applicant_id) is not int or applicant_id != self._current_user.id:
            raise PermissionError("Нельзя создать заявку от имени другого пользователя")
        if type(equipment_id) is not int or equipment_id not in self._equipment:
            raise ValueError("Указанное оборудование отсутствует в справочнике")

        request = EquipmentRequest(
            applicant_id=self._current_user.id,
            department_id=self._current_user.department_id,
            equipment_id=equipment_id,
            quantity=quantity,
            justification=justification,
        )
        self._repository.add(request)
        return request

    def update_request(self, id: int, quantity: int, justification: str) -> None:
        request = self._get_request(id)
        self._require_owner(request)
        request.update_details(quantity, justification)
        self._repository.save(request)

    def submit_request(self, id: int) -> None:
        request = self._get_request(id)
        self._require_owner(request)
        request.change_status(RequestStatus.PENDING_APPROVAL)
        self._repository.save(request)

    def approve_request(self, id: int) -> None:
        self._require_role(UserRole.MANAGER)
        request = self._get_request(id)
        request.change_status(RequestStatus.APPROVED)
        self._repository.save(request)

    def reject_request(self, id: int, reason: str) -> None:
        self._require_role(UserRole.MANAGER)
        request = self._get_request(id)
        request.decision_reason = self._require_text(reason, "причину отклонения")
        request.change_status(RequestStatus.REJECTED)
        self._repository.save(request)

    def request_clarification(self, id: int, reason: str) -> None:
        self._require_role(UserRole.MANAGER)
        request = self._get_request(id)
        request.decision_reason = self._require_text(reason, "причину возврата на уточнение")
        request.change_status(RequestStatus.NEEDS_CLARIFICATION)
        self._repository.save(request)

    def assign_specialist(self, id: int, specialist_id: int) -> None:
        self._require_role(UserRole.MANAGER)
        specialist = self._users.get(specialist_id) if type(specialist_id) is int else None
        if specialist is None or not specialist.has_role(UserRole.SPECIALIST):
            raise ValueError("Необходимо выбрать пользователя с ролью специалиста МТС")

        request = self._get_request(id)
        request.assign_specialist(specialist_id)
        request.change_status(RequestStatus.ASSIGNED)
        self._repository.save(request)

    def start_processing(self, id: int) -> None:
        self._require_role(UserRole.SPECIALIST)
        request = self._get_request(id)
        if request.assigned_specialist_id != self._current_user.id:
            raise PermissionError("Начать обработку может только назначенный специалист")
        request.change_status(RequestStatus.IN_PROGRESS)
        self._repository.save(request)

    def close_request(self, id: int, result: str) -> None:
        self._require_role(UserRole.SPECIALIST)
        request = self._get_request(id)
        if request.assigned_specialist_id != self._current_user.id:
            raise PermissionError("Закрыть заявку может только назначенный специалист")
        request.completion_result = self._require_text(result, "результат обработки")
        request.change_status(RequestStatus.CLOSED)
        self._repository.save(request)

    def get_request(self, id: int) -> EquipmentRequest:
        request = self._get_request(id)
        if not self._can_view(request):
            raise PermissionError("Нет прав на просмотр заявки другого подразделения")
        return request

    def filter_requests(
        self,
        status: RequestStatus | None = None,
        department_id: int | None = None,
        category_id: int | None = None,
    ) -> list[EquipmentRequest]:
        if status is not None and not isinstance(status, RequestStatus):
            raise ValueError("Указан некорректный статус заявки")
        self._validate_filter_id(department_id, "department_id")
        self._validate_filter_id(category_id, "category_id")

        result = []
        for request in self._repository.list_all():
            if not self._can_view(request):
                continue
            if status is not None and request.status != status:
                continue
            if department_id is not None and request.department_id != department_id:
                continue
            if category_id is not None:
                item = self._equipment.get(request.equipment_id)
                if item is None or item.category_id != category_id:
                    continue
            result.append(request)
        return result
