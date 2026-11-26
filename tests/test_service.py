import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from equipment_requests.bootstrap import create_repository, create_service
from equipment_requests.data.reference_data import EQUIPMENT, USERS
from equipment_requests.domain.enums import RequestStatus, UserRole
from equipment_requests.domain.models import EquipmentRequest
from equipment_requests.services.request_service import RequestService


class RequestServiceTests(unittest.TestCase):
    PETROV = 1
    SMIRNOVA = 2
    IVANOVA = 3
    KOZLOV = 4
    SOKOLOVA = 5
    VOLKOV = 6

    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.repository = create_repository(Path(directory.name) / "requests.db")
        self.applicant = create_service(self.repository, self.PETROV)
        self.manager = create_service(self.repository, self.IVANOVA)
        self.specialist = create_service(self.repository, self.KOZLOV)

    def make_request(
        self, user_id: int = PETROV, equipment_id: int = 1
    ) -> EquipmentRequest:
        return create_service(self.repository, user_id).create_request(
            user_id, equipment_id, 2, "Для рабочего места"
        )

    def make_pending(self) -> EquipmentRequest:
        request = self.make_request()
        self.applicant.submit_request(request.id)
        return self.repository.get_by_id(request.id)

    def make_approved(self) -> EquipmentRequest:
        request = self.make_pending()
        self.manager.approve_request(request.id)
        return self.repository.get_by_id(request.id)

    def make_assigned(self) -> EquipmentRequest:
        request = self.make_approved()
        self.manager.assign_specialist(request.id, self.KOZLOV)
        return self.repository.get_by_id(request.id)

    def make_in_progress(self) -> EquipmentRequest:
        request = self.make_assigned()
        self.specialist.start_processing(request.id)
        return self.repository.get_by_id(request.id)

    def assert_operation_rejected(self, exception, operation, *args) -> None:
        before = self.repository.list_all()
        with self.assertRaises(exception):
            operation(*args)
        self.assertEqual(self.repository.list_all(), before)

    def test_create_request_for_all_users(self) -> None:
        expected_departments = {1: 1, 2: 2, 3: 3, 4: 3, 5: 3, 6: 1}
        ids = set()
        for user_id, department_id in expected_departments.items():
            with self.subTest(user_id=user_id):
                request = self.make_request(user_id)
                self.assertGreater(request.id, 0)
                self.assertNotIn(request.id, ids)
                ids.add(request.id)
                self.assertEqual(request.applicant_id, user_id)
                self.assertEqual(request.department_id, department_id)
                self.assertEqual(request.status, RequestStatus.CREATED)
                self.assertEqual(self.repository.get_by_id(request.id), request)
        self.assertEqual(len(self.repository.list_all()), len(expected_departments))

    def test_create_for_another_user_is_forbidden(self) -> None:
        for user in USERS:
            service = create_service(self.repository, user.id)
            other_id = self.SMIRNOVA if user.id == self.PETROV else self.PETROV
            with self.subTest(user_id=user.id):
                self.assert_operation_rejected(
                    PermissionError, service.create_request,
                    other_id, 1, 2, "Для рабочего места"
                )

    def test_invalid_equipment_is_rejected(self) -> None:
        for equipment_id in (0, -1, 999, True, "1", None):
            with self.subTest(equipment_id=equipment_id):
                self.assert_operation_rejected(
                    ValueError, self.applicant.create_request,
                    self.PETROV, equipment_id, 2, "Для рабочего места"
                )

    def test_invalid_request_details_are_rejected(self) -> None:
        for quantity, justification in (
            (0, "Для работы"), (-1, "Для работы"), (True, "Для работы"),
            (1.5, "Для работы"), (2, ""), (2, " \n\t"), (2, None),
        ):
            with self.subTest(quantity=quantity, justification=justification):
                self.assert_operation_rejected(
                    ValueError, self.applicant.create_request,
                    self.PETROV, 1, quantity, justification
                )

    def test_all_roles_can_update_and_submit_own_request(self) -> None:
        for user_id in (self.PETROV, self.IVANOVA, self.KOZLOV):
            with self.subTest(user_id=user_id):
                service = create_service(self.repository, user_id)
                request = self.make_request(user_id)
                service.update_request(request.id, 3, "  Замена оборудования  ")
                saved = self.repository.get_by_id(request.id)
                self.assertEqual(saved.quantity, 3)
                self.assertEqual(saved.justification, "Замена оборудования")
                self.assertEqual(saved.status, RequestStatus.CREATED)
                self.assertEqual(saved.created_at, request.created_at)
                service.submit_request(request.id)
                self.assertEqual(
                    self.repository.get_by_id(request.id).status,
                    RequestStatus.PENDING_APPROVAL,
                )

    def test_other_users_cannot_update_or_submit_request(self) -> None:
        request = self.make_request()
        for user_id in (self.VOLKOV, self.SMIRNOVA, self.IVANOVA, self.KOZLOV):
            service = create_service(self.repository, user_id)
            for operation, args in (
                (service.update_request, (request.id, 9, "Чужая заявка")),
                (service.submit_request, (request.id,)),
            ):
                with self.subTest(user_id=user_id, operation=operation.__name__):
                    self.assert_operation_rejected(PermissionError, operation, *args)

    def test_invalid_update_preserves_request(self) -> None:
        request = self.make_request()
        for quantity, justification in ((0, "Замена"), (2, " ")):
            with self.subTest(quantity=quantity, justification=justification):
                self.assert_operation_rejected(
                    ValueError, self.applicant.update_request,
                    request.id, quantity, justification
                )

    def test_pending_request_cannot_be_edited_or_resubmitted(self) -> None:
        request = self.make_pending()
        self.assert_operation_rejected(
            ValueError, self.applicant.update_request, request.id, 3, "Замена"
        )
        self.assert_operation_rejected(
            ValueError, self.applicant.submit_request, request.id
        )

    def test_full_lifecycle(self) -> None:
        request = self.make_request()
        steps = (
            (self.applicant.submit_request, (request.id,), RequestStatus.PENDING_APPROVAL),
            (self.manager.approve_request, (request.id,), RequestStatus.APPROVED),
            (self.manager.assign_specialist, (request.id, self.KOZLOV), RequestStatus.ASSIGNED),
            (self.specialist.start_processing, (request.id,), RequestStatus.IN_PROGRESS),
            (self.specialist.close_request, (request.id, "  Оборудование получено  "), RequestStatus.CLOSED),
        )
        for operation, args, expected_status in steps:
            operation(*args)
            with self.subTest(operation=operation.__name__):
                saved = self.repository.get_by_id(request.id)
                self.assertEqual(saved.status, expected_status)
                self.assertEqual(saved.id, request.id)
                self.assertEqual(saved.created_at, request.created_at)
        saved = self.applicant.get_request(request.id)
        self.assertEqual(saved.assigned_specialist_id, self.KOZLOV)
        self.assertEqual(saved.completion_result, "Оборудование получено")
        self.assertEqual(len(self.repository.list_all()), 1)

    def test_manager_can_approve_and_assign_own_request(self) -> None:
        request = self.make_request(self.IVANOVA)
        self.assert_operation_rejected(ValueError, self.manager.approve_request, request.id)
        self.manager.update_request(request.id, 3, "Для отдела МТС")
        self.manager.submit_request(request.id)
        self.manager.approve_request(request.id)
        self.manager.assign_specialist(request.id, self.KOZLOV)
        saved = self.manager.get_request(request.id)
        self.assertEqual(saved.applicant_id, self.IVANOVA)
        self.assertEqual(saved.department_id, 3)
        self.assertEqual(saved.assigned_specialist_id, self.KOZLOV)
        self.assertEqual(saved.status, RequestStatus.ASSIGNED)

    def test_clarification_and_resubmission_keep_same_request(self) -> None:
        request = self.make_pending()
        self.manager.request_clarification(request.id, "  Уточнить количество  ")
        saved = self.applicant.get_request(request.id)
        self.assertEqual(saved.status, RequestStatus.NEEDS_CLARIFICATION)
        self.assertEqual(saved.decision_reason, "Уточнить количество")
        self.applicant.update_request(request.id, 4, "Для новых сотрудников")
        self.applicant.submit_request(request.id)
        saved = self.applicant.get_request(request.id)
        self.assertEqual(saved.status, RequestStatus.PENDING_APPROVAL)
        self.assertEqual(saved.quantity, 4)
        self.assertEqual(saved.justification, "Для новых сотрудников")
        self.assertIsNone(saved.decision_reason)
        self.assertEqual(saved.created_at, request.created_at)
        self.assertEqual(len(self.repository.list_all()), 1)
        self.manager.approve_request(request.id)
        self.assertEqual(self.applicant.get_request(request.id).status, RequestStatus.APPROVED)

    def test_rejection_preserves_reason_and_is_terminal(self) -> None:
        request = self.make_pending()
        self.manager.reject_request(request.id, "  Нет бюджета  ")
        saved = self.applicant.get_request(request.id)
        self.assertEqual(saved.status, RequestStatus.REJECTED)
        self.assertEqual(saved.decision_reason, "Нет бюджета")
        for operation, args in (
            (self.applicant.submit_request, (request.id,)),
            (self.applicant.update_request, (request.id, 3, "Замена")),
            (self.manager.approve_request, (request.id,)),
            (self.manager.assign_specialist, (request.id, self.KOZLOV)),
        ):
            with self.subTest(operation=operation.__name__):
                self.assert_operation_rejected(ValueError, operation, *args)

    def test_manager_decisions_require_reason(self) -> None:
        request = self.make_pending()
        for operation in (self.manager.reject_request, self.manager.request_clarification):
            for reason in ("", " \n\t", None):
                with self.subTest(operation=operation.__name__, reason=reason):
                    self.assert_operation_rejected(ValueError, operation, request.id, reason)

    def test_manager_decisions_require_pending_status(self) -> None:
        request = self.make_request()
        for operation, args in (
            (self.manager.approve_request, (request.id,)),
            (self.manager.reject_request, (request.id, "Нет бюджета")),
            (self.manager.request_clarification, (request.id, "Уточнить количество")),
        ):
            with self.subTest(operation=operation.__name__):
                self.assert_operation_rejected(ValueError, operation, *args)
        self.applicant.submit_request(request.id)
        self.manager.approve_request(request.id)
        self.assert_operation_rejected(ValueError, self.manager.approve_request, request.id)

    def test_only_manager_can_make_decisions(self) -> None:
        request = self.make_pending()
        for service in (self.applicant, self.specialist):
            for operation, args in (
                (service.approve_request, (request.id,)),
                (service.reject_request, (request.id, "Нет бюджета")),
                (service.request_clarification, (request.id, "Уточнить количество")),
            ):
                with self.subTest(service=service is self.specialist, operation=operation.__name__):
                    self.assert_operation_rejected(PermissionError, operation, *args)

    def test_only_manager_can_assign_specialist(self) -> None:
        request = self.make_approved()
        for service in (self.applicant, self.specialist):
            with self.subTest(service=service is self.specialist):
                self.assert_operation_rejected(
                    PermissionError, service.assign_specialist, request.id, self.KOZLOV
                )

    def test_assignment_requires_valid_specialist(self) -> None:
        request = self.make_approved()
        for specialist_id in (self.PETROV, self.IVANOVA, 999, 0, True, "4"):
            with self.subTest(specialist_id=specialist_id):
                self.assert_operation_rejected(
                    ValueError, self.manager.assign_specialist, request.id, specialist_id
                )
        self.manager.assign_specialist(request.id, self.SOKOLOVA)
        self.assertEqual(self.repository.get_by_id(request.id).assigned_specialist_id, self.SOKOLOVA)

    def test_assignment_requires_approved_status(self) -> None:
        request = self.make_pending()
        self.assert_operation_rejected(
            ValueError, self.manager.assign_specialist, request.id, self.KOZLOV
        )
        self.manager.approve_request(request.id)
        self.manager.assign_specialist(request.id, self.KOZLOV)
        self.assert_operation_rejected(
            ValueError, self.manager.assign_specialist, request.id, self.SOKOLOVA
        )

    def test_only_assigned_specialist_can_start_and_close(self) -> None:
        request = self.make_assigned()
        for user_id in (self.PETROV, self.IVANOVA, self.SOKOLOVA):
            service = create_service(self.repository, user_id)
            with self.subTest(user_id=user_id, operation="start"):
                self.assert_operation_rejected(PermissionError, service.start_processing, request.id)
        self.specialist.start_processing(request.id)
        for user_id in (self.PETROV, self.IVANOVA, self.SOKOLOVA):
            service = create_service(self.repository, user_id)
            with self.subTest(user_id=user_id, operation="close"):
                self.assert_operation_rejected(
                    PermissionError, service.close_request, request.id, "Получено"
                )
        self.specialist.close_request(request.id, "Получено")
        self.assertEqual(self.repository.get_by_id(request.id).status, RequestStatus.CLOSED)

    def test_processing_requires_correct_status(self) -> None:
        request = self.make_assigned()
        self.assert_operation_rejected(
            ValueError, self.specialist.close_request, request.id, "Получено"
        )
        self.specialist.start_processing(request.id)
        self.assert_operation_rejected(ValueError, self.specialist.start_processing, request.id)
        self.specialist.close_request(request.id, "Получено")
        self.assert_operation_rejected(
            ValueError, self.specialist.close_request, request.id, "Повторное закрытие"
        )
        self.assert_operation_rejected(ValueError, self.specialist.start_processing, request.id)

    def test_close_requires_nonblank_result(self) -> None:
        request = self.make_in_progress()
        for result in ("", " \n\t", None):
            with self.subTest(result=result):
                self.assert_operation_rejected(
                    ValueError, self.specialist.close_request, request.id, result
                )

    def test_view_access_for_all_users(self) -> None:
        requests = {user.id: self.make_request(user.id) for user in USERS}
        allowed = {
            self.PETROV: {self.PETROV, self.VOLKOV},
            self.SMIRNOVA: {self.SMIRNOVA},
            self.VOLKOV: {self.PETROV, self.VOLKOV},
            self.IVANOVA: set(requests),
            self.KOZLOV: set(requests),
            self.SOKOLOVA: set(requests),
        }
        for user_id, visible_owners in allowed.items():
            service = create_service(self.repository, user_id)
            with self.subTest(user_id=user_id, operation="list"):
                self.assertEqual(
                    {r.id for r in service.filter_requests()},
                    {requests[owner].id for owner in visible_owners},
                )
            for owner_id, request in requests.items():
                with self.subTest(user_id=user_id, owner_id=owner_id, operation="get"):
                    if owner_id in visible_owners:
                        self.assertEqual(service.get_request(request.id), request)
                    else:
                        with self.assertRaises(PermissionError):
                            service.get_request(request.id)

    def test_filters_individually_and_in_combination(self) -> None:
        first = self.make_pending()  # ИТ, компьютерная техника
        second = self.make_request(self.VOLKOV, 3)  # ИТ, оргтехника
        third = self.make_request(self.SMIRNOVA, 3)  # бухгалтерия, оргтехника
        create_service(self.repository, self.SMIRNOVA).submit_request(third.id)
        fourth = self.make_request(self.IVANOVA, 5)  # МТС, сетевое оборудование
        cases = (
            ({}, {first.id, second.id, third.id, fourth.id}),
            ({"status": RequestStatus.PENDING_APPROVAL}, {first.id, third.id}),
            ({"department_id": 1}, {first.id, second.id}),
            ({"category_id": 2}, {second.id, third.id}),
            ({"department_id": 1, "category_id": 2}, {second.id}),
            ({"status": RequestStatus.PENDING_APPROVAL, "department_id": 2, "category_id": 2}, {third.id}),
            ({"status": RequestStatus.CLOSED}, set()),
        )
        for filters, expected_ids in cases:
            with self.subTest(filters=filters):
                self.assertEqual(
                    {r.id for r in self.manager.filter_requests(**filters)}, expected_ids
                )

    def test_filters_cannot_expand_view_permissions(self) -> None:
        own = self.make_request(self.PETROV, 3)
        self.make_request(self.SMIRNOVA, 3)
        self.make_request(self.IVANOVA, 3)
        self.assertEqual(self.applicant.filter_requests(department_id=2), [])
        self.assertEqual(self.applicant.filter_requests(department_id=3), [])
        self.assertEqual(
            [r.id for r in self.applicant.filter_requests(category_id=2)], [own.id]
        )

    def test_invalid_filters_are_rejected(self) -> None:
        for filters in (
            {"status": "CREATED"}, {"status": 1},
            {"department_id": 0}, {"department_id": True},
            {"category_id": -1}, {"category_id": "2"},
        ):
            with self.subTest(filters=filters):
                with self.assertRaises(ValueError):
                    self.manager.filter_requests(**filters)

    def test_empty_repository_returns_empty_list(self) -> None:
        self.assertEqual(self.manager.filter_requests(), [])
        self.assertEqual(self.applicant.filter_requests(), [])

    def test_missing_and_invalid_request_ids(self) -> None:
        for request_id in (0, -1, True, "1", None):
            with self.subTest(request_id=request_id):
                with self.assertRaises(ValueError):
                    self.applicant.get_request(request_id)
        with self.assertRaises(KeyError):
            self.manager.get_request(999)
        self.assert_operation_rejected(KeyError, self.manager.approve_request, 999)

    def test_invalid_current_user_is_rejected(self) -> None:
        petrov = next(user for user in USERS if user.id == self.PETROV)
        for user in (replace(petrov, id=999), replace(petrov, role=UserRole.MANAGER)):
            with self.subTest(user=user):
                with self.assertRaises(ValueError):
                    RequestService(self.repository, user, USERS, EQUIPMENT)
        for user_id in (0, -1, True, 999, "1"):
            with self.subTest(user_id=user_id):
                with self.assertRaises(ValueError):
                    create_service(self.repository, user_id)


if __name__ == "__main__":
    unittest.main()
