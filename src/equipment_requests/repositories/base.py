from abc import ABC, abstractmethod

from equipment_requests.domain.models import EquipmentRequest


class RequestRepository(ABC):
    @abstractmethod
    def add(self, request: EquipmentRequest) -> None:
        ...

    @abstractmethod
    def get_by_id(self, id: int) -> EquipmentRequest:
        ...

    @abstractmethod
    def list_all(self) -> list[EquipmentRequest]:
        ...

    @abstractmethod
    def save(self, request: EquipmentRequest) -> None:
        ...
