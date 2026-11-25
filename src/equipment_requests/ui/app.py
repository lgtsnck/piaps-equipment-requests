import sqlite3
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, simpledialog, ttk

from equipment_requests.bootstrap import create_service
from equipment_requests.data.reference_data import CATEGORIES, DEPARTMENTS, EQUIPMENT, USERS
from equipment_requests.domain.enums import RequestStatus, UserRole
from equipment_requests.domain.models import Equipment, EquipmentRequest
from equipment_requests.repositories.base import RequestRepository


ROLE_LABELS = {
    UserRole.APPLICANT: "Заявитель",
    UserRole.MANAGER: "Руководитель МТС",
    UserRole.SPECIALIST: "Специалист МТС",
}

STATUS_LABELS = {
    RequestStatus.CREATED: "Создана",
    RequestStatus.PENDING_APPROVAL: "На согласовании",
    RequestStatus.NEEDS_CLARIFICATION: "На уточнении",
    RequestStatus.APPROVED: "Согласована",
    RequestStatus.REJECTED: "Отклонена",
    RequestStatus.ASSIGNED: "Назначена",
    RequestStatus.IN_PROGRESS: "В работе",
    RequestStatus.CLOSED: "Закрыта",
}


class RequestDialog(simpledialog.Dialog):
    def __init__(
        self,
        parent: tk.Misc,
        equipment: tuple[Equipment, ...],
        request: EquipmentRequest | None = None,
    ) -> None:
        self._equipment = equipment
        self._request = request
        category_names = {category.id: category.name for category in CATEGORIES}
        self._equipment_options = {
            f"{item.name} ({category_names.get(item.category_id, 'без категории')})": item.id
            for item in equipment
        }
        self._equipment_var = tk.StringVar(value=next(iter(self._equipment_options), ""))
        self._quantity_var = tk.StringVar(value=str(request.quantity) if request else "1")
        self._justification_field: tk.Text
        self.result: tuple[int, int, str] | None = None
        title = "Изменение заявки" if request else "Создание заявки"
        super().__init__(parent, title)

    def body(self, master: tk.Frame) -> ttk.Entry:
        master.columnconfigure(1, weight=1)
        ttk.Label(master, text="Оборудование:").grid(row=0, column=0, sticky="w", padx=8, pady=8)

        if self._request is None:
            choice = ttk.Combobox(
                master,
                textvariable=self._equipment_var,
                values=tuple(self._equipment_options),
                state="readonly",
                width=42,
            )
            choice.grid(row=0, column=1, sticky="ew", padx=8, pady=8)
        else:
            equipment_name = next(
                (label for label, item_id in self._equipment_options.items()
                 if item_id == self._request.equipment_id),
                f"Оборудование №{self._request.equipment_id}",
            )
            ttk.Label(master, text=equipment_name).grid(
                row=0, column=1, sticky="w", padx=8, pady=8
            )

        ttk.Label(master, text="Количество:").grid(row=1, column=0, sticky="w", padx=8, pady=8)
        quantity_field = ttk.Entry(master, textvariable=self._quantity_var, width=12)
        quantity_field.grid(row=1, column=1, sticky="w", padx=8, pady=8)

        ttk.Label(master, text="Обоснование:").grid(row=2, column=0, sticky="nw", padx=8, pady=8)
        self._justification_field = tk.Text(master, width=50, height=6, wrap="word")
        self._justification_field.grid(row=2, column=1, sticky="nsew", padx=8, pady=8)
        if self._request is not None:
            self._justification_field.insert("1.0", self._request.justification)
        return quantity_field

    def buttonbox(self) -> None:
        buttons = ttk.Frame(self)
        ttk.Button(buttons, text="Сохранить", command=self.ok).pack(side="left", padx=5)
        ttk.Button(buttons, text="Отмена", command=self.cancel).pack(side="left", padx=5)
        buttons.pack(pady=(0, 12))
        self.bind("<Escape>", self.cancel)

    def validate(self) -> bool:
        try:
            quantity = int(self._quantity_var.get().strip())
        except ValueError:
            messagebox.showerror("Некорректные данные", "Укажите целое количество оборудования.", parent=self)
            return False
        if quantity <= 0:
            messagebox.showerror("Некорректные данные", "Количество должно быть больше нуля.", parent=self)
            return False
        if not self._justification_field.get("1.0", "end").strip():
            messagebox.showerror("Некорректные данные", "Укажите обоснование приобретения.", parent=self)
            return False
        return True

    def apply(self) -> None:
        equipment_id = (
            self._request.equipment_id
            if self._request is not None
            else self._equipment_options[self._equipment_var.get()]
        )
        self.result = (
            equipment_id,
            int(self._quantity_var.get().strip()),
            self._justification_field.get("1.0", "end").strip(),
        )


class TextDialog(simpledialog.Dialog):
    def __init__(self, parent: tk.Misc, request_id: int, title: str) -> None:
        self._request_id = request_id
        self._title = title
        self._text_field: tk.Text
        self.result: str | None = None
        super().__init__(parent, title)

    def body(self, master: tk.Frame) -> tk.Text:
        ttk.Label(master, text=f"Заявка №{self._request_id}").grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 4)
        )
        ttk.Label(master, text=f"{self._title}:").grid(
            row=1, column=0, sticky="w", padx=10, pady=(0, 4)
        )
        self._text_field = tk.Text(master, width=65, height=7, wrap="word")
        self._text_field.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
        return self._text_field

    def buttonbox(self) -> None:
        buttons = ttk.Frame(self)
        ttk.Button(buttons, text="Сохранить", command=self.ok).pack(side="left", padx=5)
        ttk.Button(buttons, text="Отмена", command=self.cancel).pack(side="left", padx=5)
        buttons.pack(pady=(0, 12))
        self.bind("<Escape>", self.cancel)

    def validate(self) -> bool:
        if not self._text_field.get("1.0", "end").strip():
            messagebox.showerror(
                "Некорректные данные",
                f"Укажите {self._title.lower()}.",
                parent=self,
            )
            return False
        return True

    def apply(self) -> None:
        self.result = self._text_field.get("1.0", "end").strip()


class EquipmentRequestsApp(tk.Tk):
    def __init__(self, repository: RequestRepository) -> None:
        super().__init__()
        self.title("Учёт заявок на приобретение оборудования")
        self.geometry("1200x780")
        self.minsize(990, 660)

        self._repository = repository
        self._users = {user.id: user for user in USERS}
        self._equipment = {item.id: item for item in EQUIPMENT}
        self._departments = {item.id: item.name for item in DEPARTMENTS}
        self._categories = {item.id: item.name for item in CATEGORIES}
        self._user_options = {
            f"{user.full_name} — {ROLE_LABELS[user.role]}": user.id for user in USERS
        }
        self._specialist_options = {
            user.full_name: user.id for user in USERS if user.role == UserRole.SPECIALIST
        }
        self._status_options = {"Все состояния": None}
        self._status_options.update({label: status for status, label in STATUS_LABELS.items()})
        self._department_options = {"Все подразделения": None}
        self._department_options.update({item.name: item.id for item in DEPARTMENTS})
        self._category_options = {"Все категории": None}
        self._category_options.update({item.name: item.id for item in CATEGORIES})

        self._user_var = tk.StringVar(value=next(iter(self._user_options)))
        self._status_var = tk.StringVar(value="Все состояния")
        self._department_var = tk.StringVar(value="Все подразделения")
        self._category_var = tk.StringVar(value="Все категории")
        self._specialist_var = tk.StringVar(value=next(iter(self._specialist_options)))
        self._message_var = tk.StringVar(value="Готово")

        self._current_user_id = self._user_options[self._user_var.get()]
        self._service = create_service(self._repository, self._current_user_id)
        self._action_buttons: dict[str, ttk.Button] = {}
        self._build_widgets()
        self._configure_department_filter()
        self._refresh()

    def _build_widgets(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        header = ttk.Frame(self, padding=(12, 10))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="Текущий пользователь:").grid(row=0, column=0, padx=(0, 10))
        user_box = ttk.Combobox(
            header,
            textvariable=self._user_var,
            values=tuple(self._user_options),
            state="readonly",
            width=43,
        )
        user_box.grid(row=0, column=1, sticky="w")
        user_box.bind("<<ComboboxSelected>>", self._change_user)
        ttk.Label(
            header,
            text="Демонстрационный режим — без аутентификации",
        ).grid(row=0, column=2, sticky="e", padx=(10, 0))

        filters = ttk.LabelFrame(self, text="Фильтрация заявок", padding=10)
        filters.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        for column in range(3):
            filters.columnconfigure(column, weight=1)
        self._add_filter(filters, 0, "Состояние", self._status_var, self._status_options)
        self._department_filter = self._add_filter(
            filters, 1, "Подразделение", self._department_var, self._department_options
        )
        self._add_filter(filters, 2, "Категория", self._category_var, self._category_options)
        ttk.Button(filters, text="Сбросить фильтры", command=self._reset_filters).grid(
            row=0, column=3, rowspan=2, padx=(12, 0), sticky="s"
        )

        table_frame = ttk.LabelFrame(self, text="Заявки", padding=(8, 8))
        table_frame.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 8))
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        columns = (
            "id", "status", "date", "applicant", "department", "equipment", "quantity", "specialist"
        )
        self._table = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        headings = {
            "id": ("№", 55),
            "status": ("Состояние", 138),
            "date": ("Дата создания", 135),
            "applicant": ("Заявитель", 140),
            "department": ("Подразделение", 145),
            "equipment": ("Оборудование", 145),
            "quantity": ("Кол-во", 75),
            "specialist": ("Исполнитель", 150),
        }
        for key, (heading, width) in headings.items():
            self._table.heading(key, text=heading)
            self._table.column(key, width=width, minwidth=55, stretch=(key != "id"), anchor="w")
        self._table.grid(row=0, column=0, sticky="nsew")
        self._table.bind("<<TreeviewSelect>>", self._selection_changed)
        vertical = ttk.Scrollbar(table_frame, orient="vertical", command=self._table.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=self._table.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self._table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)

        details = ttk.LabelFrame(self, text="Сведения о выбранной заявке", padding=(8, 8))
        details.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 8))
        details.columnconfigure(0, weight=1)
        self._details = tk.Text(details, height=6, wrap="word", state="disabled", relief="flat", padx=7, pady=6)
        self._details.grid(row=0, column=0, sticky="ew")
        details_scroll = ttk.Scrollbar(details, orient="vertical", command=self._details.yview)
        details_scroll.grid(row=0, column=1, sticky="ns")
        self._details.configure(yscrollcommand=details_scroll.set)

        actions = ttk.LabelFrame(self, text="Действия", padding=(10, 10))
        actions.grid(row=4, column=0, sticky="ew", padx=12, pady=(0, 6))
        upper = ttk.Frame(actions)
        upper.pack(fill="x", pady=(0, 6))
        lower = ttk.Frame(actions)
        lower.pack(fill="x")
        for key, label, handler in (
            ("create", "Создать", self._create_request),
            ("edit", "Изменить", self._edit_request),
            ("submit", "На согласование", self._submit_request),
            ("approve", "Согласовать", self._approve_request),
            ("clarify", "Вернуть на уточнение", self._clarify_request),
            ("reject", "Отклонить", self._reject_request),
        ):
            self._add_action(upper, key, label, handler)

        ttk.Label(lower, text="Специалист:").pack(side="left", padx=(0, 5))
        self._specialist_box = ttk.Combobox(
            lower,
            textvariable=self._specialist_var,
            values=tuple(self._specialist_options),
            state="readonly",
            width=24,
        )
        self._specialist_box.pack(side="left", padx=(0, 8))
        self._add_action(lower, "assign", "Назначить", self._assign_specialist)
        self._add_action(lower, "start", "Начать обработку", self._start_processing)
        self._add_action(lower, "close", "Закрыть заявку", self._close_request)
        ttk.Button(lower, text="Обновить список", command=self._refresh).pack(side="right")

        ttk.Label(self, textvariable=self._message_var, padding=(12, 5), anchor="w").grid(
            row=5, column=0, sticky="ew"
        )

    def _add_filter(
        self,
        parent: ttk.LabelFrame,
        column: int,
        label: str,
        variable: tk.StringVar,
        options: dict[str, object],
    ) -> ttk.Combobox:
        ttk.Label(parent, text=label).grid(row=0, column=column, sticky="w")
        combo = ttk.Combobox(
            parent, textvariable=variable, values=tuple(options), state="readonly", width=24
        )
        combo.grid(row=1, column=column, sticky="ew", padx=(0, 8))
        combo.bind("<<ComboboxSelected>>", lambda _: self._refresh())
        return combo

    def _add_action(self, parent: ttk.Frame, key: str, label: str, handler) -> None:
        button = ttk.Button(parent, text=label, command=handler)
        button.pack(side="left", padx=(0, 7))
        self._action_buttons[key] = button

    def _configure_department_filter(self) -> None:
        user = self._users[self._current_user_id]
        if user.role == UserRole.APPLICANT:
            department_name = self._departments[user.department_id]
            self._department_filter.configure(values=(department_name,))
            self._department_var.set(department_name)
        else:
            self._department_filter.configure(values=tuple(self._department_options))
            self._department_var.set("Все подразделения")

    def _change_user(self, _event=None) -> None:
        self._current_user_id = self._user_options[self._user_var.get()]
        self._service = create_service(self._repository, self._current_user_id)
        self._configure_department_filter()
        self._refresh()

    def _reset_filters(self) -> None:
        self._status_var.set("Все состояния")
        self._category_var.set("Все категории")
        self._configure_department_filter()
        self._refresh()

    @staticmethod
    def _date_label(value: datetime) -> str:
        return value.astimezone().strftime("%d.%m.%Y %H:%M") if value.tzinfo else value.strftime("%d.%m.%Y %H:%M")

    def _refresh(self, focus_id: int | None = None) -> None:
        selected = self._table.selection()
        previous_id = focus_id if focus_id is not None else (int(selected[0]) if selected else None)
        try:
            requests = self._service.filter_requests(
                status=self._status_options[self._status_var.get()],
                department_id=self._department_options[self._department_var.get()],
                category_id=self._category_options[self._category_var.get()],
            )
        except (ValueError, PermissionError, KeyError, sqlite3.Error) as exc:
            messagebox.showerror("Ошибка загрузки", str(exc), parent=self)
            return
        for item in self._table.get_children():
            self._table.delete(item)
        for request in requests:
            applicant = self._users.get(request.applicant_id)
            specialist = self._users.get(request.assigned_specialist_id)
            equipment = self._equipment.get(request.equipment_id)
            self._table.insert(
                "", "end", iid=str(request.id), values=(
                    request.id,
                    STATUS_LABELS.get(request.status, request.status),
                    self._date_label(request.created_at),
                    applicant.full_name if applicant else f"№{request.applicant_id}",
                    self._departments.get(request.department_id, f"№{request.department_id}"),
                    equipment.name if equipment else f"№{request.equipment_id}",
                    request.quantity,
                    specialist.full_name if specialist else "—",
                ),
            )
        if previous_id is not None and self._table.exists(str(previous_id)):
            self._table.selection_set(str(previous_id))
            self._table.focus(str(previous_id))
            self._table.see(str(previous_id))
        else:
            self._show_details(None)
        self._update_actions()
        self._message_var.set(f"Отображено заявок: {len(requests)}")

    def _selection_changed(self, _event=None) -> None:
        self._show_details(self._selected_request())
        self._update_actions()

    def _selected_request(self) -> EquipmentRequest | None:
        selection = self._table.selection()
        if not selection:
            return None
        try:
            return self._service.get_request(int(selection[0]))
        except (KeyError, PermissionError):
            return None

    def _show_details(self, request: EquipmentRequest | None) -> None:
        if request is None:
            content = "Выберите заявку в списке для просмотра сведений и доступных действий."
        else:
            equipment = self._equipment.get(request.equipment_id)
            category = self._categories.get(equipment.category_id) if equipment else None
            specialist = self._users.get(request.assigned_specialist_id)
            content = (
                f"Заявка №{request.id} · {STATUS_LABELS[request.status]} · "
                f"Создана {self._date_label(request.created_at)}\n"
                f"Оборудование: {equipment.name if equipment else request.equipment_id} · "
                f"Категория: {category or '—'} · Количество: {request.quantity}\n"
                f"Обоснование: {request.justification}\n"
                f"Исполнитель: {specialist.full_name if specialist else 'не назначен'}\n"
                f"Причина решения: {request.decision_reason or '—'}\n"
                f"Результат обработки: {request.completion_result or '—'}"
            )
        self._details.configure(state="normal")
        self._details.delete("1.0", "end")
        self._details.insert("1.0", content)
        self._details.configure(state="disabled")

    def _update_actions(self) -> None:
        selected = self._table.selection()
        request = self._selected_request() if selected else None
        role = self._users[self._current_user_id].role
        owned = request is not None and request.applicant_id == self._current_user_id
        assigned = request is not None and request.assigned_specialist_id == self._current_user_id
        status = request.status if request else None
        active = {
            "create": True,
            "edit": owned and status in (RequestStatus.CREATED, RequestStatus.NEEDS_CLARIFICATION),
            "submit": owned and status in (RequestStatus.CREATED, RequestStatus.NEEDS_CLARIFICATION),
            "approve": (
                role == UserRole.MANAGER
                and status == RequestStatus.PENDING_APPROVAL
            ),
            "clarify": role == UserRole.MANAGER and status == RequestStatus.PENDING_APPROVAL,
            "reject": role == UserRole.MANAGER and status == RequestStatus.PENDING_APPROVAL,
            "assign": role == UserRole.MANAGER and status == RequestStatus.APPROVED,
            "start": role == UserRole.SPECIALIST and assigned and status == RequestStatus.ASSIGNED,
            "close": role == UserRole.SPECIALIST and assigned and status == RequestStatus.IN_PROGRESS,
        }
        for key, enabled in active.items():
            self._action_buttons[key].configure(state="normal" if enabled else "disabled")
        self._specialist_box.configure(state="readonly" if active["assign"] else "disabled")

    def _execute(self, operation, success_message: str, focus_id: int | None = None) -> bool:
        try:
            operation()
        except (ValueError, PermissionError, KeyError, sqlite3.Error) as exc:
            messagebox.showerror("Операция не выполнена", str(exc), parent=self)
            return False
        self._refresh(focus_id=focus_id)
        self._message_var.set(success_message)
        return True

    def _create_request(self) -> None:
        dialog = RequestDialog(self, EQUIPMENT)
        if dialog.result is None:
            return
        equipment_id, quantity, justification = dialog.result
        created: list[EquipmentRequest] = []

        def create() -> None:
            created.append(self._service.create_request(
                applicant_id=self._current_user_id,
                equipment_id=equipment_id,
                quantity=quantity,
                justification=justification,
            ))

        if self._execute(create, "Заявка успешно создана") and created:
            if self._table.exists(str(created[0].id)):
                self._table.selection_set(str(created[0].id))
                self._table.see(str(created[0].id))
            self._message_var.set(f"Создана заявка №{created[0].id}")

    def _edit_request(self) -> None:
        request = self._selected_request()
        if request is None:
            return
        dialog = RequestDialog(self, EQUIPMENT, request)
        if dialog.result is None:
            return
        _, quantity, justification = dialog.result
        self._execute(
            lambda: self._service.update_request(request.id, quantity, justification),
            f"Заявка №{request.id} изменена",
            request.id,
        )

    def _submit_request(self) -> None:
        self._apply_selected(self._service.submit_request, "отправлена на согласование")

    def _approve_request(self) -> None:
        self._apply_selected(self._service.approve_request, "согласована")

    def _reject_request(self) -> None:
        self._apply_with_text("Причина отклонения", self._service.reject_request, "отклонена")

    def _clarify_request(self) -> None:
        self._apply_with_text("Причина возврата на уточнение", self._service.request_clarification, "возвращена на уточнение")

    def _assign_specialist(self) -> None:
        request = self._selected_request()
        if request is None:
            return
        specialist_id = self._specialist_options[self._specialist_var.get()]
        self._execute(
            lambda: self._service.assign_specialist(request.id, specialist_id),
            f"Для заявки №{request.id} назначен специалист",
            request.id,
        )

    def _start_processing(self) -> None:
        self._apply_selected(self._service.start_processing, "передана в работу")

    def _close_request(self) -> None:
        request = self._selected_request()
        if request is None:
            return
        dialog = TextDialog(self, request.id, "Результат обработки")
        if dialog.result is None:
            return
        self._execute(
            lambda: self._service.close_request(request.id, dialog.result),
            f"Заявка №{request.id} закрыта",
            request.id,
        )

    def _apply_selected(self, operation, past_tense: str) -> None:
        request = self._selected_request()
        if request is None:
            return
        self._execute(lambda: operation(request.id), f"Заявка №{request.id} {past_tense}", request.id)

    def _apply_with_text(self, title: str, operation, past_tense: str) -> None:
        request = self._selected_request()
        if request is None:
            return
        dialog = TextDialog(self, request.id, title)
        if dialog.result is None:
            return
        self._execute(
            lambda: operation(request.id, dialog.result),
            f"Заявка №{request.id} {past_tense}",
            request.id,
        )
