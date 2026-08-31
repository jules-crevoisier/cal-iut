"""Couche d'accès données pour les comptes utilisateurs — mêmes conventions
que `PlanningRepository` (`db/repository.py`) : une classe fine autour d'une
`Session` SQLAlchemy, aucune logique métier (normalisation d'email, décision
`ADMIN_EMAILS`...) qui appartient à `api/accounts.py`."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from cal_iut.db.models import EmailToken, User


class AccountRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_email(self, email: str) -> User | None:
        return self.db.query(User).filter(User.email == email).first()

    def get_by_id(self, user_id: int) -> User | None:
        return self.db.get(User, user_id)

    def create_pending_user(self, email: str, password_hash: str) -> User:
        user = User(email=email, password_hash=password_hash, role="read_only", status="pending_email")
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def mark_email_confirmed(self, user: User) -> None:
        """L'email est confirmé — deux issues possibles : les adresses de
        `ADMIN_EMAILS` sautent directement en admin actif (aucune personne
        n'a besoin de les activer), tout le reste attend qu'un admin déjà
        actif fixe un rôle (`activate`/`PATCH /admin/users/{id}`)."""
        from cal_iut.api.accounts import ADMIN_EMAILS

        user.email_confirmed_at = datetime.now(UTC)
        if user.email in ADMIN_EMAILS:
            user.role = "admin"
            user.status = "active"
            user.activated_at = datetime.now(UTC)
        else:
            user.status = "pending_admin_activation"
        self.db.commit()

    def activate(self, user: User, role: str, activated_by: int) -> None:
        user.role = role
        user.status = "active"
        user.activated_at = datetime.now(UTC)
        user.activated_by = activated_by
        self.db.commit()

    def set_role(self, user: User, role: str) -> None:
        user.role = role
        self.db.commit()

    def set_status(self, user: User, status: str) -> None:
        user.status = status
        self.db.commit()

    def count_active_admins(self) -> int:
        return (
            self.db.query(User)
            .filter(User.role == "admin", User.status == "active")
            .count()
        )

    def list_users(self, status: str | None = None) -> list[User]:
        q = self.db.query(User).order_by(User.id)
        if status:
            q = q.filter(User.status == status)
        return q.all()

    def create_token(self, user_id: int, token_hash: str, purpose: str, expires_at: datetime) -> EmailToken:
        token = EmailToken(user_id=user_id, token_hash=token_hash, purpose=purpose, expires_at=expires_at)
        self.db.add(token)
        self.db.commit()
        self.db.refresh(token)
        return token

    def get_valid_token(self, token_hash: str, purpose: str) -> EmailToken | None:
        now = datetime.now(UTC)
        return (
            self.db.query(EmailToken)
            .filter(
                EmailToken.token_hash == token_hash,
                EmailToken.purpose == purpose,
                EmailToken.used_at.is_(None),
                EmailToken.expires_at > now,
            )
            .first()
        )

    def consume_token(self, token: EmailToken) -> None:
        token.used_at = datetime.now(UTC)
        self.db.commit()

    def invalidate_outstanding_tokens(self, user_id: int, purpose: str) -> None:
        now = datetime.now(UTC)
        (
            self.db.query(EmailToken)
            .filter(
                EmailToken.user_id == user_id,
                EmailToken.purpose == purpose,
                EmailToken.used_at.is_(None),
            )
            .update({EmailToken.used_at: now}, synchronize_session=False)
        )
        self.db.commit()
