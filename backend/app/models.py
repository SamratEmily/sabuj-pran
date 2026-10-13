"""Import every module's models here so Alembic autogenerate and tests see all tables."""

from app.core.db import Base
from app.modules.admin import models as admin_models  # noqa: F401
from app.modules.approvals import models as approvals_models  # noqa: F401
from app.modules.auth import models as auth_models  # noqa: F401
from app.modules.employees import models as employees_models  # noqa: F401
from app.modules.inventory import models as inventory_models  # noqa: F401
from app.modules.master import models as master_models  # noqa: F401
from app.modules.money import models as money_models  # noqa: F401
from app.modules.parties import models as parties_models  # noqa: F401
from app.modules.purchase import models as purchase_models  # noqa: F401
from app.modules.sales import models as sales_models  # noqa: F401

__all__ = ["Base"]
