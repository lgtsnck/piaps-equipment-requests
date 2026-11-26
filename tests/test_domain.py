import unittest
from dataclasses import replace
from datetime import datetime, timezone

from equipment_requests.domain.enums import RequestStatus, UserRole
from equipment_requests.domain.models import EquipmentRequest, User


class UserTests(unittest.TestCase):
    def test_has_role(self) -> None:
        for role in UserRole:
            user = User(id=1, full_name="Тестовый пользователь", role=role, department_id=1)
            for checked_role in UserRole:
                with self.subTest(role=role, checked_role=checked_role):
                    self.assertEqual(user.has_role(checked_role), role == checked_role)


class EquipmentRequestTests(unittest.TestCase):
    @staticmethod
    def make_request(**overrides) -> EquipmentRequest:
        data = {
            "applicant_id": 1,
            "department_id": 1,
            "equipment_id": 1,
            "quantity": 2,
            "justification": "Для рабочего места",
        }
        data.update(overrides)
        return EquipmentRequest(**data)

    def test_new_request_defaults(self) -> None:
        request = self.make_request(justification="  Для рабочего места  ")

        self.assertEqual(request.id, 0)
        self.assertEqual(request.applicant_id, 1)
        self.assertEqual(request.department_id, 1)
        self.assertEqual(request.equipment_id, 1)
        self.assertEqual(request.quantity, 2)
        self.assertEqual(request.justification, "Для рабочего места")
        self.assertEqual(request.status, RequestStatus.CREATED)
        self.assertIsInstance(request.created_at, datetime)
        self.assertEqual(request.created_at.tzinfo, timezone.utc)
        self.assertIsNone(request.assigned_specialist_id)
        self.assertIsNone(request.decision_reason)
        self.assertIsNone(request.completion_result)

    def test_invalid_required_ids(self) -> None:
        for field in ("applicant_id", "department_id", "equipment_id"):
            for value in (0, -1, True, 1.5, "1", None):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        self.make_request(**{field: value})

    def test_invalid_request_id(self) -> None:
        for value in (-1, True, 1.5, "1", None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.make_request(id=value)

    def test_invalid_created_at_and_status(self) -> None:
        for overrides in (
            {"created_at": None},
            {"created_at": "2026-11-26"},
            {"status": "CREATED"},
            {"status": None},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    self.make_request(**overrides)

    def test_invalid_assigned_specialist_id(self) -> None:
        for value in (0, -1, True, 1.5, "1"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.make_request(assigned_specialist_id=value)

    def test_invalid_quantity(self) -> None:
        for quantity in (0, -1, True, 1.5, "2", None):
            with self.subTest(quantity=quantity):
                with self.assertRaises(ValueError):
                    self.make_request(quantity=quantity)

    def test_invalid_justification(self) -> None:
        for justification in ("", "  \t\n", None, 123):
            with self.subTest(justification=justification):
                with self.assertRaises(ValueError):
                    self.make_request(justification=justification)

    def test_update_in_allowed_statuses(self) -> None:
        for status in (RequestStatus.CREATED, RequestStatus.NEEDS_CLARIFICATION):
            with self.subTest(status=status):
                request = self.make_request(id=7, status=status)
                expected = replace(request, quantity=3, justification="Уточнённая потребность")

                request.update_details(3, "  Уточнённая потребность  ")

                self.assertEqual(request, expected)

    def test_update_in_other_statuses_is_forbidden(self) -> None:
        for status in RequestStatus:
            if status in (RequestStatus.CREATED, RequestStatus.NEEDS_CLARIFICATION):
                continue
            with self.subTest(status=status):
                request = self.make_request(status=status)
                before = replace(request)
                with self.assertRaises(ValueError):
                    request.update_details(3, "Новое обоснование")
                self.assertEqual(request, before)

    def test_invalid_update_leaves_request_unchanged(self) -> None:
        for status in (RequestStatus.CREATED, RequestStatus.NEEDS_CLARIFICATION):
            for quantity, justification in ((0, "Обоснование"), (True, "Обоснование"), (3, " "), (3, None)):
                with self.subTest(status=status, quantity=quantity, justification=justification):
                    request = self.make_request(status=status)
                    before = replace(request)
                    with self.assertRaises(ValueError):
                        request.update_details(quantity, justification)
                    self.assertEqual(request, before)

    def test_assign_specialist_to_approved_request(self) -> None:
        request = self.make_request(status=RequestStatus.APPROVED)
        request.assign_specialist(4)

        self.assertEqual(request.assigned_specialist_id, 4)
        self.assertEqual(request.status, RequestStatus.APPROVED)
        request.change_status(RequestStatus.ASSIGNED)
        self.assertEqual(request.status, RequestStatus.ASSIGNED)

    def test_assignment_in_other_statuses_is_forbidden(self) -> None:
        for status in RequestStatus:
            if status == RequestStatus.APPROVED:
                continue
            with self.subTest(status=status):
                request = self.make_request(status=status)
                before = replace(request)
                with self.assertRaises(ValueError):
                    request.assign_specialist(4)
                self.assertEqual(request, before)

    def test_assignment_with_invalid_id_is_forbidden(self) -> None:
        for specialist_id in (0, -1, True, 1.5, "4", None):
            with self.subTest(specialist_id=specialist_id):
                request = self.make_request(status=RequestStatus.APPROVED)
                before = replace(request)
                with self.assertRaises(ValueError):
                    request.assign_specialist(specialist_id)
                self.assertEqual(request, before)

    def test_transition_matrix(self) -> None:
        # Ожидаемые переходы заданы независимо от реализации модели.
        allowed = {
            (RequestStatus.CREATED, RequestStatus.PENDING_APPROVAL),
            (RequestStatus.PENDING_APPROVAL, RequestStatus.APPROVED),
            (RequestStatus.PENDING_APPROVAL, RequestStatus.REJECTED),
            (RequestStatus.PENDING_APPROVAL, RequestStatus.NEEDS_CLARIFICATION),
            (RequestStatus.NEEDS_CLARIFICATION, RequestStatus.PENDING_APPROVAL),
            (RequestStatus.APPROVED, RequestStatus.ASSIGNED),
            (RequestStatus.ASSIGNED, RequestStatus.IN_PROGRESS),
            (RequestStatus.IN_PROGRESS, RequestStatus.CLOSED),
        }
        for source in RequestStatus:
            for target in RequestStatus:
                with self.subTest(source=source, target=target):
                    # Реквизиты перехода заполнены, чтобы проверять именно граф состояний.
                    request = self.make_request(
                        status=source,
                        assigned_specialist_id=4,
                        decision_reason="Решение руководителя",
                        completion_result="Оборудование приобретено",
                    )
                    before = replace(request)
                    expected = (source, target) in allowed
                    self.assertEqual(request.can_transition_to(target), expected)
                    if expected:
                        request.change_status(target)
                        self.assertEqual(request.status, target)
                    else:
                        with self.assertRaises(ValueError):
                            request.change_status(target)
                        self.assertEqual(request, before)

    def test_invalid_transition_target_type(self) -> None:
        for target in ("PENDING_APPROVAL", None, 1):
            with self.subTest(target=target):
                request = self.make_request()
                before = replace(request)
                self.assertFalse(request.can_transition_to(target))
                with self.assertRaises(ValueError):
                    request.change_status(target)
                self.assertEqual(request, before)

    def test_manager_decision_requires_reason(self) -> None:
        for target in (RequestStatus.NEEDS_CLARIFICATION, RequestStatus.REJECTED):
            for reason in (None, "", " \t\n"):
                with self.subTest(target=target, reason=reason):
                    request = self.make_request(status=RequestStatus.PENDING_APPROVAL, decision_reason=reason)
                    before = replace(request)
                    with self.assertRaises(ValueError):
                        request.change_status(target)
                    self.assertEqual(request, before)

    def test_assigned_status_requires_specialist(self) -> None:
        request = self.make_request(status=RequestStatus.APPROVED)
        before = replace(request)
        with self.assertRaises(ValueError):
            request.change_status(RequestStatus.ASSIGNED)
        self.assertEqual(request, before)

    def test_closed_status_requires_result(self) -> None:
        for result in (None, "", " \t\n"):
            with self.subTest(result=result):
                request = self.make_request(
                    status=RequestStatus.IN_PROGRESS,
                    assigned_specialist_id=4,
                    completion_result=result,
                )
                before = replace(request)
                with self.assertRaises(ValueError):
                    request.change_status(RequestStatus.CLOSED)
                self.assertEqual(request, before)

    def test_full_lifecycle_with_clarification(self) -> None:
        request = self.make_request(id=7)
        created_at = request.created_at
        request.change_status(RequestStatus.PENDING_APPROVAL)
        request.decision_reason = "Уточнить количество"
        request.change_status(RequestStatus.NEEDS_CLARIFICATION)
        self.assertEqual(request.decision_reason, "Уточнить количество")
        request.update_details(3, "Уточнённая потребность")
        request.change_status(RequestStatus.PENDING_APPROVAL)
        self.assertIsNone(request.decision_reason)
        request.change_status(RequestStatus.APPROVED)
        request.assign_specialist(4)
        request.change_status(RequestStatus.ASSIGNED)
        request.change_status(RequestStatus.IN_PROGRESS)
        request.completion_result = "Оборудование приобретено"
        request.change_status(RequestStatus.CLOSED)

        self.assertEqual(request.id, 7)
        self.assertEqual(request.created_at, created_at)
        self.assertEqual(request.quantity, 3)
        self.assertEqual(request.justification, "Уточнённая потребность")
        self.assertEqual(request.assigned_specialist_id, 4)
        self.assertEqual(request.completion_result, "Оборудование приобретено")
        self.assertEqual(request.status, RequestStatus.CLOSED)
        self.assertFalse(any(request.can_transition_to(status) for status in RequestStatus))

    def test_rejected_request_is_terminal(self) -> None:
        request = self.make_request()
        request.change_status(RequestStatus.PENDING_APPROVAL)
        request.decision_reason = "Потребность не подтверждена"
        request.change_status(RequestStatus.REJECTED)

        self.assertEqual(request.status, RequestStatus.REJECTED)
        self.assertEqual(request.decision_reason, "Потребность не подтверждена")
        self.assertIsNone(request.assigned_specialist_id)
        self.assertFalse(any(request.can_transition_to(status) for status in RequestStatus))


if __name__ == "__main__":
    unittest.main()
