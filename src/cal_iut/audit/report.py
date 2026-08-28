"""Structure de restitution de l'audit."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Severity(StrEnum):
    """Trois niveaux, dans l'ordre où ils doivent être traités.

    `ERREUR` est réservé à ce qui produit — ou produira — un emploi du temps
    faux ou absent. `ALERTE` signale une donnée probablement mal comprise, qui
    demande un œil humain avant de lancer une année. `INFO` documente ce que
    l'audit a regardé sans rien trouver, ou ce qu'il ne sait pas vérifier :
    c'est justement là que se cachent les bugs de demain.
    """

    ERREUR = "erreur"
    ALERTE = "alerte"
    INFO = "info"


@dataclass
class Finding:
    """Un constat d'audit.

    `quoi_faire` est obligatoire dans l'esprit sinon dans le type : un constat
    qu'on ne sait pas corriger ne sert à personne, et l'outil est destiné à des
    utilisateurs qui ne liront jamais le code.
    """

    severity: Severity
    check: str  # identifiant stable, ex. "config.cours_inexistant"
    message: str
    quoi_faire: str = ""
    ou: str = ""  # fichier / ligne / clé concernée
    details: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "severite": str(self.severity),
            "controle": self.check,
            "message": self.message,
            "quoi_faire": self.quoi_faire,
            "ou": self.ou,
            "details": self.details,
        }


@dataclass
class AuditReport:
    findings: list[Finding] = field(default_factory=list)
    # Contrôles effectués sans rien trouver — affichés pour que l'utilisateur
    # sache ce qui a été VÉRIFIÉ, pas seulement ce qui a échoué.
    passed: list[str] = field(default_factory=list)

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    def ok(self, check: str, message: str) -> None:
        self.passed.append(f"{check} — {message}")

    def erreurs(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.ERREUR]

    def alertes(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.ALERTE]

    def infos(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.INFO]

    def as_dict(self) -> dict:
        return {
            "resume": {
                "erreurs": len(self.erreurs()),
                "alertes": len(self.alertes()),
                "infos": len(self.infos()),
                "controles_ok": len(self.passed),
            },
            "constats": [f.as_dict() for f in self.findings],
            "controles_ok": self.passed,
        }

    def to_text(self, *, show_ok: bool = False) -> str:
        icons = {Severity.ERREUR: "[ERREUR]", Severity.ALERTE: "[ALERTE]", Severity.INFO: "[INFO]  "}
        lines: list[str] = []
        for severity in (Severity.ERREUR, Severity.ALERTE, Severity.INFO):
            group = [f for f in self.findings if f.severity is severity]
            if not group:
                continue
            lines.append("")
            lines.append(f"{'=' * 70}")
            lines.append(f"{severity.value.upper()} ({len(group)})")
            lines.append(f"{'=' * 70}")
            for f in group:
                lines.append(f"{icons[severity]} {f.message}")
                if f.ou:
                    lines.append(f"          où   : {f.ou}")
                if f.quoi_faire:
                    lines.append(f"          faire: {f.quoi_faire}")
                for d in f.details[:8]:
                    lines.append(f"                 - {d}")
                if len(f.details) > 8:
                    lines.append(f"                 ... et {len(f.details) - 8} autre(s)")
                lines.append("")
        if show_ok and self.passed:
            lines.append(f"{'=' * 70}")
            lines.append(f"CONTRÔLES PASSÉS ({len(self.passed)})")
            lines.append(f"{'=' * 70}")
            lines.extend(f"[OK]     {p}" for p in self.passed)
        lines.append("")
        lines.append(
            f"RÉSUMÉ : {len(self.erreurs())} erreur(s), {len(self.alertes())} alerte(s), "
            f"{len(self.infos())} info(s), {len(self.passed)} contrôle(s) passé(s)."
        )
        if not self.erreurs():
            lines.append("Aucune erreur bloquante.")
        return "\n".join(lines)
