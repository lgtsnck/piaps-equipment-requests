from equipment_requests.bootstrap import create_repository
from equipment_requests.ui.app import EquipmentRequestsApp


def main() -> None:
    application = EquipmentRequestsApp(create_repository())
    application.mainloop()


if __name__ == "__main__":
    main()
