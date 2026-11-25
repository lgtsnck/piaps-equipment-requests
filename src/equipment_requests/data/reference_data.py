from equipment_requests.domain.enums import UserRole
from equipment_requests.domain.models import Department, Equipment, EquipmentCategory, User


DEPARTMENTS: tuple[Department, ...] = (
    Department(id=1, name="Информационные технологии"),
    Department(id=2, name="Бухгалтерия"),
    Department(id=3, name="Отдел МТС"),
)

USERS: tuple[User, ...] = (
    User(id=1, full_name="Иван Петров", role=UserRole.APPLICANT, department_id=1),
    User(id=2, full_name="Мария Смирнова", role=UserRole.APPLICANT, department_id=2),
    User(id=3, full_name="Ольга Иванова", role=UserRole.MANAGER, department_id=3),
    User(id=4, full_name="Алексей Козлов", role=UserRole.SPECIALIST, department_id=3),
    User(id=5, full_name="Екатерина Соколова", role=UserRole.SPECIALIST, department_id=3),
    User(id=6, full_name="Сергей Волков", role=UserRole.APPLICANT, department_id=1),
)

CATEGORIES: tuple[EquipmentCategory, ...] = (
    EquipmentCategory(id=1, name="Компьютерная техника"),
    EquipmentCategory(id=2, name="Оргтехника"),
    EquipmentCategory(id=3, name="Сетевое оборудование"),
)

EQUIPMENT: tuple[Equipment, ...] = (
    Equipment(id=1, name="Ноутбук", category_id=1),
    Equipment(id=2, name="Рабочая станция", category_id=1),
    Equipment(id=3, name="Принтер", category_id=2),
    Equipment(id=4, name="МФУ", category_id=2),
    Equipment(id=5, name="Коммутатор", category_id=3),
)
