"""Reproducible performance check for NFR-03 (real SQLite + Tkinter)."""

import platform
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from equipment_requests.bootstrap import create_repository, create_service
from equipment_requests.data.reference_data import CATEGORIES, DEPARTMENTS, EQUIPMENT, USERS
from equipment_requests.domain.enums import RequestStatus, UserRole
from equipment_requests.domain.models import EquipmentRequest
from equipment_requests.repositories.base import RequestRepository
from equipment_requests.ui.app import EquipmentRequestsApp, STATUS_LABELS


REQUEST_COUNT = 1000
REPEATS = 5
LIMIT_SECONDS = 2.0


@dataclass(frozen=True)
class Scenario:
    name: str
    status: RequestStatus | None = None
    department_id: int | None = None
    category_id: int | None = None

    def filters(self) -> dict:
        return dict(status=self.status, department_id=self.department_id, category_id=self.category_id)


SCENARIOS = (
    Scenario("All requests"),
    Scenario("Status", status=RequestStatus.PENDING_APPROVAL),
    Scenario("Department", department_id=1),
    Scenario("Category", category_id=1),
    Scenario("Combined", status=RequestStatus.PENDING_APPROVAL, department_id=1, category_id=1),
)


def seed(repository: RequestRepository) -> list[EquipmentRequest]:
    """Prepare valid, deterministic fixtures outside the measured interval."""
    states = tuple(RequestStatus)
    specialists = tuple(user for user in USERS if user.role == UserRole.SPECIALIST)
    records = []
    for i in range(REQUEST_COUNT):
        user = USERS[i % len(USERS)]
        item = EQUIPMENT[(i // len(USERS)) % len(EQUIPMENT)]
        status = states[(i // (len(USERS) * len(EQUIPMENT))) % len(states)]
        request = EquipmentRequest(
            applicant_id=user.id,
            department_id=user.department_id,
            equipment_id=item.id,
            quantity=i % 5 + 1,
            justification=f"Тестовая заявка {i + 1}: приобретение оборудования",
            status=status,
            assigned_specialist_id=specialists[i % len(specialists)].id
            if status in (RequestStatus.ASSIGNED, RequestStatus.IN_PROGRESS, RequestStatus.CLOSED)
            else None,
            decision_reason="Тестовая причина решения"
            if status in (RequestStatus.NEEDS_CLARIFICATION, RequestStatus.REJECTED)
            else None,
            completion_result="Оборудование приобретено" if status == RequestStatus.CLOSED else None,
        )
        repository.add(request)
        records.append(request)
    return records


def expected_ids(records: list[EquipmentRequest], scenario: Scenario) -> list[int]:
    """Calculate the expected selection from fixtures, independently of the service."""
    categories = {item.id: item.category_id for item in EQUIPMENT}
    return [
        record.id
        for record in records
        if (scenario.status is None or record.status == scenario.status)
        and (scenario.department_id is None or record.department_id == scenario.department_id)
        and (scenario.category_id is None or categories[record.equipment_id] == scenario.category_id)
    ]


def apply_filters(app: EquipmentRequestsApp, scenario: Scenario) -> None:
    """Use the same variables and refresh handler as the real filter controls."""
    department_names = {department.id: department.name for department in DEPARTMENTS}
    category_names = {category.id: category.name for category in CATEGORIES}
    app._status_var.set(STATUS_LABELS[scenario.status] if scenario.status is not None else "Все состояния")
    app._department_var.set(department_names[scenario.department_id] if scenario.department_id is not None else "Все подразделения")
    app._category_var.set(category_names[scenario.category_id] if scenario.category_id is not None else "Все категории")
    app._refresh()
    app.update()  # Process pending layout, redraw and selection events.


def check_ids(actual: list[int], expected: list[int], label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: unexpected IDs (rows: {len(actual)}, expected: {len(expected)})")


def table_ids(app: EquipmentRequestsApp) -> list[int]:
    return [int(item) for item in app._table.get_children()]


def run_benchmark(repository: RequestRepository, records: list[EquipmentRequest]) -> bool:
    manager = next(user for user in USERS if user.role == UserRole.MANAGER)
    service = create_service(repository, manager.id)
    all_ids = [record.id for record in records]
    full = SCENARIOS[0]
    combined = SCENARIOS[-1]

    # Keep the real application window visible during measurement.
    app = EquipmentRequestsApp(repository)
    try:
        app.update()
        print(f"Python: {platform.python_version()} | OS: {platform.platform()}")
        print(f"SQLite: {sqlite3.sqlite_version} | Tcl: {app.tk.call('info', 'patchlevel')} | Tk: {app.tk.call('package', 'provide', 'Tk')}")
        print(f"NFR-03 | Requests: {len(records)} | Repeats: {REPEATS} | Limit: {LIMIT_SECONDS:.3f} s")
        print("Keep the application window visible; do not interact during measurement.", flush=True)

        # The application initially opens as an ordinary employee. Measure the
        # first complete list when changing to the manager (all 1000 rows).
        start = perf_counter()
        app._user_var.set(next(label for label, user_id in app._user_options.items() if user_id == manager.id))
        app._change_user()
        app.update()
        first_full = perf_counter() - start
        check_ids(table_ids(app), all_ids, "First full list")
        print(f"First full list: {len(all_ids)} rows, {first_full:.6f} s", flush=True)
        print()
        print(f"{'Scenario':<18}{'Rows':>6}{'Svc med, s':>13}{'Svc max, s':>13}{'UI med, s':>13}{'UI max, s':>13}{'Result':>9}")
        print("-" * 85)
        worst = first_full
        passed = first_full <= LIMIT_SECONDS

        for scenario in SCENARIOS:
            expected = expected_ids(records, scenario)
            if not expected:
                raise AssertionError(f"Empty fixture selection: {scenario.name}")
            service_times = []
            ui_times = []
            for _ in range(REPEATS):
                start = perf_counter()
                result = service.filter_requests(**scenario.filters())
                service_times.append(perf_counter() - start)
                check_ids([request.id for request in result], expected, f"Service: {scenario.name}")

                # Begin filtered runs with a full table; begin full-list runs
                # with a filtered table. Preparation is not included in timing.
                baseline = combined if scenario == full else full
                apply_filters(app, baseline)
                check_ids(table_ids(app), expected_ids(records, baseline), "UI baseline")
                start = perf_counter()
                apply_filters(app, scenario)
                ui_times.append(perf_counter() - start)
                check_ids(table_ids(app), expected, f"UI: {scenario.name}")

            service_max, ui_max = max(service_times), max(ui_times)
            ok = max(service_max, ui_max) <= LIMIT_SECONDS
            passed = passed and ok
            worst = max(worst, service_max, ui_max)
            print(f"{scenario.name:<18}{len(expected):>6}{median(service_times):>13.6f}{service_max:>13.6f}"
                  f"{median(ui_times):>13.6f}{ui_max:>13.6f}{'PASS' if ok else 'FAIL':>9}", flush=True)

        print("-" * 85)
        print(f"Maximum observed time: {worst:.6f} s")
        print(f"NFR-03: {'PASS' if passed else 'FAIL'}", flush=True)
        return passed
    finally:
        app.destroy()


def main() -> int:
    with TemporaryDirectory(prefix="piaps_performance_") as directory:
        repository = create_repository(Path(directory) / "requests.db")
        records = seed(repository)
        check_ids([request.id for request in repository.list_all()], [record.id for record in records], "Seed")
        # Avoid blocking the automated run with a modal message box on error.
        with patch("equipment_requests.ui.app.messagebox.showerror", side_effect=RuntimeError("Application reported a loading error")):
            return 0 if run_benchmark(repository, records) else 1


if __name__ == "__main__":
    sys.exit(main())
