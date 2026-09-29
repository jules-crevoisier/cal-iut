/**
 * Mail, nom et intitulé : les compléter quand ils manquent, les CORRIGER
 * quand ils sont faux (29/09/2026, suite de « il faut pouvoir ajouter l'info
 * et l'enregistrer » : « go » pour corriger une valeur du fichier).
 *
 * - valeur absente : pastille « Ajouter » (`MailManquant`) ;
 * - valeur présente : la valeur, puis un crayon discret « Modifier » (révélé
 *   au survol, visible au focus clavier), même champ en ligne ;
 * - valeur modifiée dans l'appli : marque « modifiée » ; au survol ou au
 *   focus, la valeur du fichier et « Revenir à la valeur du fichier ».
 *
 * La saisie a le dernier mot sur la configuration (`api/reference.py`) ; la
 * marque est là pour qu'on ne corrige jamais le fichier sans savoir qu'une
 * saisie passe devant. Lecture seule : la valeur et la marque, sans bouton.
 */

import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import {
  completerContactEnseignant,
  completerCours,
  completerEnseignant,
  retablirValeurFichier,
} from "../api/client";
import { useDroits } from "../contexts/Droits";
import type { SurchargeReference } from "../types/app";
import { ChampEnLigne, validerEmail } from "./ChampEnLigne";

function dateCourte(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" });
}

/** Marque « modifiée dans l'appli », avec la valeur d'origine et, pour qui
 *  peut modifier, « Revenir à la valeur du fichier ».
 *
 *  La bulle est rendue dans `document.body` (portail), en position fixe sous
 *  la marque : les tableaux qui défilent (annuaire, Référence) portent un
 *  masque de fondu (`mask-image`) qui rognait tout ce qui en dépassait,
 *  même en position fixe. Montrée au survol et au focus de la marque ;
 *  Entrée (ou un clic) l'épingle et place le focus sur « Revenir à la
 *  valeur du fichier » ; Échap la ferme et rend le focus à la marque. */
export function MarqueModifiee({
  surcharge,
  libelleChamp,
  onRevenir,
}: {
  surcharge: SurchargeReference;
  libelleChamp: string;
  /** Absent en lecture seule. */
  onRevenir?: () => Promise<void>;
}) {
  const [epinglee, setEpinglee] = useState(false);
  const [survol, setSurvol] = useState(false);
  const [focus, setFocus] = useState(false);
  // Échap : masquée jusqu'à ce que le focus quitte la marque (sinon le
  // focus rendu à la marque la rouvrirait aussitôt).
  const [masquee, setMasquee] = useState(false);
  const [envoi, setEnvoi] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const hote = useRef<HTMLSpanElement>(null);
  const bouton = useRef<HTMLButtonElement>(null);
  const bulle = useRef<HTMLSpanElement>(null);
  const idBulle = useId();
  const fermeture = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [position, setPosition] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
  const visible = !masquee && (epinglee || survol || focus);

  const placer = useCallback(() => {
    const r = hote.current?.getBoundingClientRect();
    if (!r) return;
    const largeur = Math.min(320, window.innerWidth * 0.8);
    setPosition({ top: r.bottom + 2, left: Math.max(8, Math.min(r.left, window.innerWidth - largeur - 8)) });
  }, []);
  useEffect(() => {
    if (!visible) return;
    placer();
    window.addEventListener("scroll", placer, true);
    window.addEventListener("resize", placer);
    return () => {
      window.removeEventListener("scroll", placer, true);
      window.removeEventListener("resize", placer);
    };
  }, [visible, placer]);
  useEffect(() => {
    if (epinglee) bulle.current?.querySelector<HTMLElement>("button")?.focus();
  }, [epinglee]);
  useEffect(() => () => {
    if (fermeture.current) clearTimeout(fermeture.current);
  }, []);

  const entrer = () => {
    if (fermeture.current) clearTimeout(fermeture.current);
    setSurvol(true);
  };
  // Petit délai : le temps de passer de la marque à la bulle sans qu'elle
  // se referme sous la souris.
  const sortir = () => {
    fermeture.current = setTimeout(() => setSurvol(false), 150);
  };
  const fermer = () => {
    setEpinglee(false);
    setMasquee(true);
    bouton.current?.focus();
  };
  const origine = surcharge.origine ?? null;
  const quand = dateCourte(surcharge.modifie_le);

  return (
    <span ref={hote} className="marque-modifiee" data-pas-ouvrir="" onMouseEnter={entrer} onMouseLeave={sortir}>
      <button
        ref={bouton}
        type="button"
        className="marque-modifiee-bouton"
        aria-expanded={visible}
        aria-controls={idBulle}
        aria-label={`${libelleChamp} : modifiée dans l'appli. Valeur du fichier : ${origine ?? "aucune"}`}
        onFocus={() => setFocus(true)}
        onBlur={(e) => {
          if (!bulle.current?.contains(e.relatedTarget as Node | null)) {
            setFocus(false);
            setMasquee(false);
          }
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.preventDefault();
            setEpinglee(false);
            setMasquee(true);
          }
        }}
        onClick={() => {
          setMasquee(false);
          setEpinglee((o) => !o);
        }}
      >
        modifiée
      </button>
      {visible &&
        createPortal(
          <span
            ref={bulle}
            id={idBulle}
            className="marque-modifiee-bulle"
            role="group"
            aria-label={`Origine — ${libelleChamp}`}
            style={{ top: position.top, left: position.left }}
            onMouseEnter={entrer}
            onMouseLeave={sortir}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.preventDefault();
                fermer();
              }
            }}
            onBlur={(e) => {
              const vers = e.relatedTarget as Node | null;
              if (!bulle.current?.contains(vers) && vers !== bouton.current) {
                setEpinglee(false);
                setFocus(false);
              }
            }}
          >
            <span>
              Modifiée dans l'appli{quand ? ` le ${quand}` : ""}
              {surcharge.modifie_par ? ` par ${surcharge.modifie_par}` : ""}.
            </span>
            <span>
              Valeur du fichier : {origine ? <strong>{origine}</strong> : <em>aucune</em>}
            </span>
            {onRevenir && (
              <button
                type="button"
                className="btn btn--sm"
                disabled={envoi}
                onClick={async () => {
                  setEnvoi(true);
                  setErreur(null);
                  try {
                    await onRevenir();
                    fermer();
                  } catch (err) {
                    setErreur(err instanceof Error ? err.message : "Retour impossible.");
                  } finally {
                    setEnvoi(false);
                  }
                }}
              >
                {envoi ? "Retour…" : "Revenir à la valeur du fichier"}
              </button>
            )}
            {erreur && (
              <span className="champ-en-ligne-erreur" role="alert">
                {erreur}
              </span>
            )}
          </span>,
          document.body,
        )}
    </span>
  );
}

/**
 * Mail manquant : « Ajouter » ouvre le champ en ligne pour qui peut
 * compléter (rôle `edit` ou `admin`) ; la pastille « manquant » seule en
 * lecture seule. Partagé par l'annuaire, la fiche et « Liens & partage ».
 */
export function MailManquant({
  code,
  nom,
  libelleBouton = "Ajouter",
  libelleLectureSeule = "manquant",
  lectureSeule,
  onEnregistre,
}: {
  code: string;
  nom: string;
  libelleBouton?: string;
  libelleLectureSeule?: string;
  /** Rendu propre à l'écran en lecture seule (sinon la pastille « manquant »). */
  lectureSeule?: ReactNode;
  /** Après un enregistrement réussi (retour affiché par l'écran). */
  onEnregistre?: (email: string) => void;
}) {
  const { peutCompleter, apresEnregistrement } = useDroits();
  if (!peutCompleter) return <>{lectureSeule ?? <span className="pill dot warn">{libelleLectureSeule}</span>}</>;
  return (
    <ChampEnLigne
      libelleBouton={libelleBouton}
      libelleChamp={`Adresse mail de ${nom}`}
      type="email"
      placeholder="prenom.nom@univ-reims.fr"
      valider={validerEmail}
      onEnregistrer={async (email) => {
        await completerContactEnseignant(code, email);
        onEnregistre?.(email);
        apresEnregistrement();
      }}
    />
  );
}

/** Retour visible et annoncé après « Revenir à la valeur du fichier » : la
 *  marque disparaît au rechargement, ce mot reste. */
function useRetour(): [ReactNode, () => void] {
  const [retabli, setRetabli] = useState(false);
  const noeud = (
    <span className="retour-reference" role="status" aria-live="polite">
      {retabli && <span className="pill dot good">valeur du fichier rétablie</span>}
    </span>
  );
  return [noeud, () => setRetabli(true)];
}

/**
 * Le mail d'un enseignant, présent : la valeur (`affichage`), le crayon
 * « Modifier » et, s'il a été modifié dans l'appli, la marque. Absent :
 * `MailManquant`.
 */
export function EmailEnseignant({
  code,
  nom,
  email,
  surcharge,
  affichage,
  onEnregistre,
  manquant,
}: {
  code: string;
  nom: string;
  email: string;
  surcharge?: SurchargeReference;
  /** Rendu de la valeur (lien mailto, texte tronqué…) ; rien = crayon seul. */
  affichage?: ReactNode;
  onEnregistre?: (email: string) => void;
  /** Rendu quand le mail manque (défaut : `MailManquant`). */
  manquant?: ReactNode;
}) {
  const { peutCompleter, apresEnregistrement } = useDroits();
  const [retour, signalerRetour] = useRetour();
  if (!email) return <>{manquant ?? <MailManquant code={code} nom={nom} onEnregistre={onEnregistre} />}</>;
  const libelle = `Adresse mail de ${nom}`;
  const marque = surcharge ? (
    <MarqueModifiee
      surcharge={surcharge}
      libelleChamp={libelle}
      onRevenir={
        peutCompleter
          ? async () => {
              await retablirValeurFichier("enseignants", code, "contact");
              signalerRetour();
              apresEnregistrement();
            }
          : undefined
      }
    />
  ) : null;
  if (!peutCompleter) {
    return (
      <span className="valeur-modifiable">
        {affichage}
        {marque}
      </span>
    );
  }
  return (
    <>
      <ChampEnLigne
        mode="modifier"
        libelleChamp={libelle}
        type="email"
        valeurInitiale={email}
        valeurAffichee={affichage}
        apres={marque}
        valider={validerEmail}
        onEnregistrer={async (v) => {
          await completerContactEnseignant(code, v);
          onEnregistre?.(v);
          apresEnregistrement();
        }}
      />
      {retour}
    </>
  );
}

/** Crayon « Modifier » du nom d'un enseignant (à côté du titre de sa fiche). */
export function ModifierNomEnseignant({
  code,
  nom,
  surcharge,
}: {
  code: string;
  nom: string;
  surcharge?: SurchargeReference;
}) {
  const { peutCompleter, apresEnregistrement } = useDroits();
  const [retour, signalerRetour] = useRetour();
  const libelle = `Nom complet de ${code}`;
  const marque = surcharge ? (
    <MarqueModifiee
      surcharge={surcharge}
      libelleChamp={libelle}
      onRevenir={
        peutCompleter
          ? async () => {
              await retablirValeurFichier("enseignants", code, "nom");
              signalerRetour();
              apresEnregistrement();
            }
          : undefined
      }
    />
  ) : null;
  if (!peutCompleter) return marque;
  return (
    <>
      <ChampEnLigne
        mode="modifier"
        libelleChamp={libelle}
        valeurInitiale={nom}
        apres={marque}
        valider={(v) => (v.trim().length < 2 ? "Saisissez le prénom et le nom." : null)}
        onEnregistrer={async (v) => {
          await completerEnseignant(code, { nom: v });
          apresEnregistrement();
        }}
      />
      {retour}
    </>
  );
}

/** Crayon « Modifier » de l'intitulé d'une matière (fiche de la matière). */
export function ModifierIntituleCours({
  code,
  intitule,
  surcharge,
}: {
  code: string;
  intitule: string;
  surcharge?: SurchargeReference;
}) {
  const { peutCompleter, apresEnregistrement } = useDroits();
  const [retour, signalerRetour] = useRetour();
  const libelle = `Intitulé de ${code}`;
  const marque = surcharge ? (
    <MarqueModifiee
      surcharge={surcharge}
      libelleChamp={libelle}
      onRevenir={
        peutCompleter
          ? async () => {
              await retablirValeurFichier("cours", code, "intitule");
              signalerRetour();
              apresEnregistrement();
            }
          : undefined
      }
    />
  ) : null;
  if (!peutCompleter) return marque;
  return (
    <>
      <ChampEnLigne
        mode="modifier"
        libelleChamp={libelle}
        valeurInitiale={intitule === code ? "" : intitule}
        apres={marque}
        valider={(v) => (!v.trim() || v.trim().toUpperCase() === code.toUpperCase() ? "Saisissez l'intitulé." : null)}
        onEnregistrer={async (v) => {
          await completerCours(code, { intitule: v });
          apresEnregistrement();
        }}
      />
      {retour}
    </>
  );
}
