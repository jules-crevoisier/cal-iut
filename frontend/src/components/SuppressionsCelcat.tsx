/**
 * Les évènements que Celcat a en trop — le seul geste qui reste humain.
 *
 * Décision du 16/09/2026 : les suppressions ne s'automatisent jamais. Le
 * 08/09, dix-sept évènements ont disparu de Celcat, dont douze venus de la
 * saisie manuelle d'un collègue : un évènement peut ressortir « en trop »
 * parce qu'il fait double emploi, ou parce que quelqu'un est en train de le
 * poser à la main, et rien ne permet de les distinguer automatiquement.
 *
 * Critique design du même jour : la confirmation annonçait « 2 suppressions
 * définitives » sans dire LESQUELLES, alors que le geste réversible (voir
 * les identiques) avait droit à sa liste. On montre donc ce qu'on supprime
 * avant de demander, et la confirmation le répète.
 */
import type { CelcatComparaison } from "../api/client";
import { confirmAsync } from "../utils/confirmDialog";
import { jourDate, pluriel } from "../utils/celcatStatut";

function description(l: CelcatComparaison["lignes"][number], lundi: string | null): string {
  const c = l.celcat;
  if (!c) return l.course_code || "évènement inconnu";
  const salles = c.salles && c.salles.length ? c.salles.join(" + ") : c.salle;
  return [c.module || l.course_code, c.groupe, `${jourDate(c.jour, lundi)} ${c.heure ?? ""}`.trim(), salles]
    .filter(Boolean)
    .join(" — ");
}

export function SuppressionsCelcat({
  donnees,
  occupe,
  onSupprimer,
}: {
  donnees: CelcatComparaison;
  occupe: boolean;
  onSupprimer: () => void;
}) {
  const enTrop = (donnees.lignes ?? []).filter((l) => l.statut === "en_trop_celcat");
  if (enTrop.length === 0) return null;
  const releveFiable = !!donnees.releve_le && !donnees.perime;

  const demander = async () => {
    const liste = enTrop.map((l) => `• ${description(l, donnees.lundi)} (#${l.celcat?.event_id ?? "?"})`).join("\n");
    const ok = await confirmAsync(
      `${liste}\n\nCes évènements seront supprimés définitivement de Celcat. ` +
        "Vérifiez que personne n’est en train de les saisir à la main.",
      {
        title: `Supprimer ${pluriel(enTrop.length, "évènement")} dans Celcat`,
        confirmLabel: `Supprimer ${pluriel(enTrop.length, "évènement")}`,
      },
    );
    if (ok) onSupprimer();
  };

  return (
    <section className="panel celcat-suppressions" aria-labelledby="celcat-suppressions-titre">
      <h2 id="celcat-suppressions-titre">
        {pluriel(enTrop.length, "évènement")} en trop dans Celcat
      </h2>
      <p className="celcat-aide">
        Présents dans Celcat, absents du planning. Rien n’est supprimé sans votre accord : un évènement en trop
        peut être en cours de saisie par un collègue.
      </p>
      <ul className="celcat-liste">
        {enTrop.map((l, i) => (
          <li key={`${l.celcat?.event_id ?? i}`} className="celcat-liste-ligne">
            <span>{description(l, donnees.lundi)}</span>
            <span className="celcat-sous-texte">#{l.celcat?.event_id ?? "?"}</span>
          </li>
        ))}
      </ul>
      <div className="celcat-actions">
        <button type="button" className="btn btn--danger" disabled={occupe || !releveFiable} onClick={() => void demander()}>
          Supprimer {enTrop.length > 1 ? `ces ${enTrop.length} évènements` : "cet évènement"}
        </button>
      </div>
      {!releveFiable ? (
        <p className="celcat-texte-attention">Relisez Celcat d’abord : on ne supprime pas d’après un relevé périmé.</p>
      ) : null}
    </section>
  );
}
