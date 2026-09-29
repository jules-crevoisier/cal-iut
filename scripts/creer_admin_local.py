"""Crée (ou réactive) un compte administrateur dans la base LOCALE.

Pour le développement uniquement (captures d'écran, essais) : l'inscription
normale passe par un mail de confirmation, indisponible hors production.

    python scripts/creer_admin_local.py [email] [mot_de_passe]

Ne jamais committer la base modifiée par ce script (`git checkout
data/state/cal-iut.db` pour revenir en arrière).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cal_iut.api import accounts  # noqa: E402
from cal_iut.api.state import DB_PATH  # noqa: E402
from cal_iut.db.accounts_repository import AccountRepository  # noqa: E402
from cal_iut.db.session import get_db, init_db  # noqa: E402


def main() -> None:
    email = sys.argv[1] if len(sys.argv) > 1 else "admin@local.test"
    mot_de_passe = sys.argv[2] if len(sys.argv) > 2 else "admin-local-123"
    init_db(DB_PATH)
    repo = AccountRepository(get_db(DB_PATH))
    user = repo.get_by_email(email) or repo.create_pending_user(email, accounts.hash_password(mot_de_passe))
    repo.mark_email_confirmed(user)
    repo.activate(user, "admin", user.id)
    print(f"Compte admin actif : {email}")


if __name__ == "__main__":
    main()
