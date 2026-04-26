from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class UserContext:
    user_id: int
    username: str
    email: str
    full_name: str
    client_id: str
    client_name: str
    schema_name: str
    role: str
    department: str
    hierarchy_code: str | None = None
    salesrep_code: str | None = None
    so_code: str | None = None
    asm_code: str | None = None
    zsm_code: str | None = None
    nsm_code: str | None = None

    def profile(self) -> dict:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "email": self.email,
            "full_name": self.full_name,
            "client_id": self.client_id,
            "client_name": self.client_name,
            "schema_name": self.schema_name,
            "role": self.role,
            "department": self.department,
            "hierarchy_code": self.hierarchy_code,
            "salesrep_code": self.salesrep_code,
            "so_code": self.so_code,
            "asm_code": self.asm_code,
            "zsm_code": self.zsm_code,
            "nsm_code": self.nsm_code,
        }


current_user: ContextVar[UserContext | None] = ContextVar("current_user", default=None)
current_cube_token: ContextVar[str | None] = ContextVar("current_cube_token", default=None)
