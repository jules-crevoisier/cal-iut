import type { AppPayload } from "../types/app";
import type { IcsSession } from "./ics";

/**
 * Brouillon mailto pré-rempli — objet, corps et lien personnel prêts, le
 * destinataire venant de `teacherEmails` (saisi à la main côté serveur,
 * `data/config/teacher_contacts.yaml`, absent de tout fichier source
 * officiel). Sans adresse connue, le brouillon s'ouvre quand même avec le
 * destinataire vide plutôt que de faire disparaître le bouton — ça ferait
 * croire que la fonction ne marche pas.
 */
export function mailtoForTeacher(
  payload: Pick<AppPayload, "teacherLabels" | "teacherEmails">,
  code: string,
  items: IcsSession[],
  personalLink: string,
): string {
  const name = payload.teacherLabels[code] || code;
  const mail = payload.teacherEmails[code] || "";
  const hours = (items.reduce((n, it) => n + (it.dur || 1), 0) * 1.5).toLocaleString("fr-FR");
  const body = [
    `Bonjour ${name},`,
    "",
    `Voici votre emploi du temps : ${personalLink}`,
    "",
    `Il compte ${items.length} séance(s), soit ${hours} h.`,
    "Le lien ouvre directement votre planning ; un bouton permet d'exporter",
    "les séances vers votre agenda personnel (fichier .ics).",
    "",
    "Une question ? Contactez le 07 81 25 78 87.",
    "",
    "Cordialement,",
  ].join("\r\n");
  return `mailto:${encodeURIComponent(mail)}?subject=${encodeURIComponent(
    "Votre emploi du temps MMI",
  )}&body=${encodeURIComponent(body)}`;
}
