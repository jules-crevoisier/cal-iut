"""Crée (ou réactive) un compte dans la base LOCALE — administrateur par
défaut, ou un autre rôle avec `--role`.

Pour le développement uniquement (captures d'écran, essais) : l'inscription
normale passe par un mail de confirmation, indisponible hors production.

    python scripts/creer_admin_local.py [email] [mot_de_passe] [--role admin|edit|read_only|api]

`--role api` : compte « Accès API » (aucune donnée dans l'appli, seulement
la gestion de ses clés d'accès à l'API v1 en lecture, cf. `api/accounts.py`).

Ne jamais committer la base modifiée par ce script (`git checkout
data/state/cal-iut.db` pour revenir en arrière).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cal_iut.api import accounts  # noqa: E402
from cal_iut.api.state import DB_PATH  # noqa: E402
from cal_iut.db.accounts_repository import AccountRepository  # noqa: E402
from cal_iut.db.session import get_db, init_db  # noqa: E402


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Crée (ou réactive) un compte actif dans la base locale.")
    parser.add_argument("email", nargs="?", default="admin@local.test")
    parser.add_argument("mot_de_passe", nargs="?", default="admin-local-123")
    parser.add_argument("--role", choices=accounts.ROLES, default="admin", help="rôle du compte (défaut : admin)")
    args = parser.parse_args(argv)
    init_db(DB_PATH)
    repo = AccountRepository(get_db(DB_PATH))
    user = repo.get_by_email(args.email) or repo.create_pending_user(
        args.email, accounts.hash_password(args.mot_de_passe)
    )
    repo.mark_email_confirmed(user)
    repo.activate(user, args.role, user.id)
    print(f"Compte actif ({args.role}) : {args.email}")


if __name__ == "__main__":
    main()
