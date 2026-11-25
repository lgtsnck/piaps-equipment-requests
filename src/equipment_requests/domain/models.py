from dataclasses import dataclass, field
from datetime import datetime, timezone

from .enums import RequestStatus, UserRole


@dataclass(slots=True)
class Department:
    id: int
    name: str


@dataclass(slots=True)
class User:
    id: int
    full_name: str
    role: UserRole
    department_id: int

    def has_role(self, role: UserRole) -> bool:
        return self.role == role


@dataclass(slots=True)
class EquipmentCategory:
    id: int
    name: str


@dataclass(slots=True)
class Equipment:
    id: int
    name: str
    category_id: int


_ALLOWED_TRANSITIONS: dict[RequestStatus, frozenset[RequestStatus]] = {
    RequestStatus.CREATED: frozenset({RequestStatus.PENDING_APPROVAL}),
    RequestStatus.PENDING_APPROVAL: frozenset({
        RequestStatus.APPROVED,
        RequestStatus.REJECTED,
        RequestStatus.NEEDS_CLARIFICATION,
    }),
    RequestStatus.NEEDS_CLARIFICATION: frozenset({RequestStatus.PENDING_APPROVAL}),
    RequestStatus.APPROVED: frozenset({RequestStatus.ASSIGNED}),
    RequestStatus.REJECTED: frozenset(),
    RequestStatus.ASSIGNED: frozenset({RequestStatus.IN_PROGRESS}),
    RequestStatus.IN_PROGRESS: frozenset({RequestStatus.CLOSED}),
    RequestStatus.CLOSED: frozenset(),
}


@dataclass(slots=True, kw_only=True)
class EquipmentRequest:
    applicant_id: int
    department_id: int
    equipment_id: int
    quantity: int
    justification: str
    id: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: RequestStatus = RequestStatus.CREATED
    assigned_specialist_id: int | None = None
    decision_reason: str | None = None
    completion_result: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("applicant_id", "department_id", "equipment_id"):
            value = getattr(self, field_name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{field_name} должен быть положительным целым числом")
        if type(self.id) is not int or self.id < 0:
            raise ValueError("id должен быть неотрицательным целым числом")
        if not isinstance(self.created_at, datetime):
            raise ValueError("created_at должен быть датой и временем")
        if not isinstance(self.status, RequestStatus):
            raise ValueError("status должен быть значением RequestStatus")
        if self.assigned_specialist_id is not None and (
            type(self.assigned_specialist_id) is not int or self.assigned_specialist_id <= 0
        ):
            raise ValueError("assigned_specialist_id должен быть положительным целым числом")
        self._validate_details(self.quantity, self.justification)
        self.justification = self.justification.strip()

    @staticmethod
    def _validate_details(quantity: int, justification: str) -> None:
        if type(quantity) is not int or quantity <= 0:
            raise ValueError("Количество оборудования должно быть положительным целым числом")
        if not isinstance(justification, str) or not justification.strip():
            raise ValueError("Необходимо указать обоснование приобретения")

    def update_details(self, quantity: int, justification: str) -> None:
        if self.status not in (RequestStatus.CREATED, RequestStatus.NEEDS_CLARIFICATION):
            raise ValueError("Редактировать можно только созданную или возвращённую на уточнение заявку")
        self._validate_details(quantity, justification)
        self.quantity = quantity
        self.justification = justification.strip()

    def assign_specialist(self, specialist_id: int) -> None:
        if self.status != RequestStatus.APPROVED:
            raise ValueError("Назначить специалиста можно только для согласованной заявки")
        if type(specialist_id) is not int or specialist_id <= 0:
            raise ValueError("Необходимо указать корректный идентификатор специалиста")
        self.assigned_specialist_id = specialist_id

    def can_transition_to(self, next: RequestStatus) -> bool:
        return isinstance(next, RequestStatus) and next in _ALLOWED_TRANSITIONS[self.status]

    def change_status(self, next: RequestStatus) -> None:
        if not self.can_transition_to(next):
            raise ValueError(f"Недопустимый переход: {self.status} → {next}")
        if next in (RequestStatus.NEEDS_CLARIFICATION, RequestStatus.REJECTED):
            if not self.decision_reason or not self.decision_reason.strip():
                raise ValueError("Необходимо указать причину решения руководителя")
        if next == RequestStatus.ASSIGNED and self.assigned_specialist_id is None:
            raise ValueError("Перед назначением состояния необходимо выбрать специалиста")
        if next == RequestStatus.CLOSED:
            if not self.completion_result or not self.completion_result.strip():
                raise ValueError("Перед закрытием необходимо зафиксировать результат")
        self.status = next
        if next == RequestStatus.PENDING_APPROVAL:
            self.decision_reason = None
