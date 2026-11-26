import sqlite3
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from equipment_requests.domain.enums import RequestStatus
from equipment_requests.domain.models import EquipmentRequest
from equipment_requests.repositories.base import RequestRepository
from equipment_requests.repositories.sqlite_repository import SQLiteRequestRepository


class SQLiteRequestRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db_path = Path(directory.name) / "requests.db"
        self.repository = SQLiteRequestRepository(self.db_path)

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

    def test_repository_implements_contract(self) -> None:
        self.assertIsInstance(self.repository, RequestRepository)
        with self.assertRaises(TypeError):
            RequestRepository()

    def test_new_database_is_empty(self) -> None:
        self.assertTrue(self.db_path.is_file())
        self.assertEqual(self.repository.list_all(), [])

    def test_add_assigns_id_and_preserves_fields(self) -> None:
        created_at = datetime(2026, 11, 26, 8, 30, 15, 123456, tzinfo=timezone.utc)
        request = self.make_request(created_at=created_at)
        self.assertEqual(request.id, 0)

        self.repository.add(request)

        self.assertGreater(request.id, 0)
        loaded = self.repository.get_by_id(request.id)
        self.assertEqual(loaded, request)
        self.assertIsNot(loaded, request)
        self.assertIs(loaded.status, RequestStatus.CREATED)
        self.assertEqual(loaded.created_at.isoformat(), created_at.isoformat())
        self.assertIsNone(loaded.assigned_specialist_id)
        self.assertIsNone(loaded.decision_reason)
        self.assertIsNone(loaded.completion_result)

    def test_add_assigns_unique_ids_and_lists_in_order(self) -> None:
        requests = [self.make_request(quantity=i) for i in range(1, 4)]
        for request in requests:
            self.repository.add(request)

        ids = [request.id for request in requests]
        self.assertEqual(len(set(ids)), len(requests))
        self.assertTrue(all(id > 0 for id in ids))
        self.assertEqual(self.repository.list_all(), sorted(requests, key=lambda r: r.id))

    def test_add_existing_request_is_forbidden(self) -> None:
        request = self.make_request()
        self.repository.add(request)
        original = replace(request)

        with self.assertRaises(ValueError):
            self.repository.add(request)

        self.assertEqual(request, original)
        self.assertEqual(self.repository.list_all(), [original])

    def test_get_missing_request_raises_key_error(self) -> None:
        with self.assertRaises(KeyError):
            self.repository.get_by_id(999)

    def test_save_updates_existing_request_only(self) -> None:
        request = self.make_request()
        other = self.make_request(applicant_id=2, department_id=2)
        self.repository.add(request)
        self.repository.add(other)
        original_id = request.id
        original_date = request.created_at

        request.update_details(5, "Замена оборудования")
        request.change_status(RequestStatus.PENDING_APPROVAL)
        self.repository.save(request)

        loaded = self.repository.get_by_id(original_id)
        self.assertEqual(loaded, request)
        self.assertEqual(loaded.id, original_id)
        self.assertEqual(loaded.created_at, original_date)
        self.assertEqual(self.repository.get_by_id(other.id), other)
        self.assertEqual(len(self.repository.list_all()), 2)

    def test_save_unsaved_request_is_forbidden(self) -> None:
        request = self.make_request()

        with self.assertRaises(ValueError):
            self.repository.save(request)

        self.assertEqual(request.id, 0)
        self.assertEqual(self.repository.list_all(), [])

    def test_save_missing_request_raises_key_error(self) -> None:
        request = self.make_request(id=999)

        with self.assertRaises(KeyError):
            self.repository.save(request)

        self.assertEqual(self.repository.list_all(), [])

    def test_reopening_preserves_full_lifecycle(self) -> None:
        request = self.make_request()
        self.repository.add(request)
        request.change_status(RequestStatus.PENDING_APPROVAL)
        request.change_status(RequestStatus.APPROVED)
        request.assign_specialist(4)
        request.change_status(RequestStatus.ASSIGNED)
        request.change_status(RequestStatus.IN_PROGRESS)
        request.completion_result = "Оборудование получено.\nПередано подразделению."
        request.change_status(RequestStatus.CLOSED)
        self.repository.save(request)

        reopened = SQLiteRequestRepository(self.db_path)
        loaded = reopened.get_by_id(request.id)
        self.assertEqual(loaded, request)
        self.assertIs(loaded.status, RequestStatus.CLOSED)
        self.assertEqual(loaded.assigned_specialist_id, 4)
        self.assertEqual(loaded.completion_result, request.completion_result)
        self.assertEqual(reopened.list_all(), [request])

        another = self.make_request()
        reopened.add(another)
        self.assertGreater(another.id, request.id)

    def test_decision_reasons_persist_after_reopening(self) -> None:
        for status in (RequestStatus.REJECTED, RequestStatus.NEEDS_CLARIFICATION):
            with self.subTest(status=status):
                request = self.make_request()
                self.repository.add(request)
                request.change_status(RequestStatus.PENDING_APPROVAL)
                request.decision_reason = "Уточнение потребности.\nТребуются дополнительные сведения."
                request.change_status(status)
                self.repository.save(request)

                reopened = SQLiteRequestRepository(self.db_path)
                loaded = reopened.get_by_id(request.id)
                self.assertEqual(loaded, request)
                self.assertIs(loaded.status, status)
                self.assertEqual(loaded.decision_reason, request.decision_reason)

                if status == RequestStatus.NEEDS_CLARIFICATION:
                    loaded.update_details(3, "Потребность уточнена")
                    loaded.change_status(RequestStatus.PENDING_APPROVAL)
                    reopened.save(loaded)
                    self.assertIsNone(self.repository.get_by_id(request.id).decision_reason)
                    self.assertEqual(self.repository.get_by_id(request.id), loaded)

    def test_text_round_trip(self) -> None:
        justification = "Замена ПК № 1: 'офис'; \"учёт\".\nНужен новый комплект."
        request = self.make_request(justification=justification)
        self.repository.add(request)
        self.assertEqual(self.repository.get_by_id(request.id).justification, justification)

    def test_failed_insert_does_not_persist_invalid_data(self) -> None:
        request = self.make_request()
        # Direct mutation bypasses the domain validation; SQLite must reject it.
        request.quantity = 0

        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.add(request)

        self.assertEqual(request.id, 0)
        self.assertEqual(self.repository.list_all(), [])

    def test_failed_update_preserves_stored_data(self) -> None:
        request = self.make_request()
        self.repository.add(request)
        original = replace(request)
        request.quantity = 0
        request.justification = "Некорректное изменение"

        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.save(request)

        self.assertEqual(self.repository.get_by_id(original.id), original)
        self.assertEqual(self.repository.list_all(), [original])


if __name__ == "__main__":
    unittest.main()
