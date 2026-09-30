/**
 * Administration Celcat — un seul écran, dans l'ordre où l'on décide.
 *
 * Refonte du 16/09/2026, après une critique design notée 16/40 et ce retour
 * utilisateur : « j'ai l'impression de devoir cliquer plusieurs fois à des
 * heures différentes sur "Corriger les écarts de cette semaine" pour que ça
 * les corrige vraiment ».
 *
 * Les trois onglets (Pilotage / Activité / Contenu Celcat) suivaient la
 * tuyauterie du système : chaque pièce technique avait son panneau, et aucun
 * ne répondait d'un coup d'œil à « est-ce que ça concorde ? ». On arrivait
 * sur des réglages ; le verdict, gris, était deux clics plus loin.
 *
 * Refonte du 29/09/2026 — l'écran se lit de haut en bas, puis en deux
 * colonnes :
 *
 *   1. une barre à plat : l'état du système (écriture, robot d'envoi,
 *      lecture de Celcat) ; la semaine comparée est celle de la barre
 *      supérieure, partagée par tous les écrans (refonte v2) ;
 *   2. les compteurs en tuiles (à modifier, à créer, en trop, identiques,
 *      en file), puis le VERDICT de la semaine et le geste qui corrige,
 *      suivi jusqu'à la vérification sur une lecture fraîche de Celcat ;
 *   3. à gauche, ce qu'on regarde : les écarts séance par séance, puis les
 *      évènements en trop (seul geste resté humain) ; à droite, ce qui est
 *      en route vers Celcat et ce qui bloque ;
 *   4. repliés : l'activité et les réglages.
 *
 * Mêmes primitives que le reste de l'application (panneaux, boutons,
 * pastilles, jetons) ; styles propres dans `AdminCelcatView.css`.
 */
import { useCallback, useEffect, useState } from "react";

import {
  autoriserCreationSemaineCelcat,
  fetchAppState,
  fetchCelcatComparaison,
  fetchCelcatEtat,
  fetchCelcatExtras,
  fetchCelcatFile,
  fetchCelcatInstantane,
  fetchCelcatLogs,
  fetchCelcatMappings,
  definirMappingCelcat,
  oublierMappingCelcat,
  type CelcatComparaison,
  type CelcatEtat,
  type CelcatExtra,
  type CelcatFile,
  type CelcatInstantane,
  type CelcatLog,
  type CelcatMappings,
} from "../api/client";
import { BlocagesCelcat } from "../components/BlocagesCelcat";
import { DetailComparaisonCelcat } from "../components/DetailComparaisonCelcat";
import { EtatFileCelcat } from "../components/EtatFileCelcat";
import { JournalCelcat } from "../components/JournalCelcat";
import { ReglagesCelcat } from "../components/ReglagesCelcat";
import { StatutCelcat } from "../components/StatutCelcat";
import { SuppressionsCelcat } from "../components/SuppressionsCelcat";
import { NavigationSemaine, VerdictCelcat, type SemaineChoisissable } from "../components/VerdictCelcat";
import { useSemaineGlobale } from "../contexts/SemaineGlobale";
import { useBoucleCelcat } from "../hooks/useBoucleCelcat";
import type { AppPayload } from "../types/app";
import { indexSemaineCourante } from "../utils/semaineCourante";
import "../styles/outils.css";
import "./AdminCelcatView.css";

/** Tant que des corrections attendent, on relit la file à ce rythme. Une
 * fois vide, on arrête : un écran qui interroge le serveur sans raison est
 * un écran qu'on finit par fermer. */
const SONDAGE_FILE_MS = 10_000;

/**
 * Les semaines comparables, VALEUR = indice du solveur.
 *
 * `weekRows` est la séquence CONTINUE des semaines, vacances comprises. Le
 * sélecteur envoyait la POSITION dans cette liste comme indice : juste
 * jusqu'à la Toussaint, puis décalé d'un cran (constaté sur le payload de
 * production le 10/09/2026). Les lignes bloquées n'ont pas d'indice : elles
 * sortent de la liste — il n'y a rien à comparer une semaine fermée.
 */
function semainesDuSolveur(rows: { label: string; weekIndex: number | null }[]): SemaineChoisissable[] {
  return rows
    .filter((w): w is { label: string; weekIndex: number } => w.weekIndex !== null)
    .map((w) => ({ indice: w.weekIndex, libelle: w.label }));
}

function message(e: unknown, repli: string): string {
  return e instanceof Error ? e.message : repli;
}

/** Cadences de la boucle de vérification. Facultatives : `App` monte la vue
 * sans rien passer ; les tests les raccourcissent pour ne pas attendre des
 * minutes réelles. */
export interface CadenceCelcat {
  intervalleMs?: number;
  limiteWorkerMs?: number;
  limiteReleveMs?: number;
  sondageFileMs?: number;
}

export function AdminCelcatView({ cadence = {} }: { cadence?: CadenceCelcat } = {}) {
  const [etat, setEtat] = useState<CelcatEtat | null>(null);
  const [erreurEtat, setErreurEtat] = useState<string | null>(null);
  const [instantane, setInstantane] = useState<CelcatInstantane | null>(null);
  const [erreurInstantane, setErreurInstantane] = useState<string | null>(null);
  const [file, setFile] = useState<CelcatFile | null>(null);
  const [erreurFile, setErreurFile] = useState<string | null>(null);
  const [extras, setExtras] = useState<CelcatExtra[]>([]);
  const [logs, setLogs] = useState<CelcatLog[]>([]);
  const [semaines, setSemaines] = useState<SemaineChoisissable[]>([]);
  // Indice INTERNE de la semaine comparée. `null` tant que le calendrier n'est
  // pas chargé : mieux vaut ne pas comparer que comparer la mauvaise. Le
  // défaut était `0`, la première semaine de l'année.
  const [semaineLocale, setSemaine] = useState<number | null>(null);
  // Refonte v2 (29/09/2026) : sous la barre supérieure, la semaine comparée
  // est la semaine PARTAGÉE de l'application (on la choisit une fois, chaque
  // écran suit) ; le sélecteur local ne reste que hors de la coque.
  const semaineGlobale = useSemaineGlobale();
  const [lignes, setLignes] = useState<AppPayload["weekRows"] | null>(null);
  const ligneGlobale = semaineGlobale && lignes ? lignes[semaineGlobale.index] : undefined;
  const semaine: number | null = semaineGlobale ? (ligneGlobale?.weekIndex ?? null) : semaineLocale;
  // Semaine fermée (vacances) : rien à comparer, et on le dit.
  const semaineFermee = !!semaineGlobale && !!ligneGlobale && ligneGlobale.weekIndex === null;
  // La semaine d'aujourd'hui, pour y revenir d'un clic.
  const [courante, setCourante] = useState<number | null>(null);
  const [comparaison, setComparaison] = useState<CelcatComparaison | null>(null);
  const [erreurComparaison, setErreurComparaison] = useState<string | null>(null);
  const [mappings, setMappings] = useState<CelcatMappings | null>(null);
  const [erreurMapping, setErreurMapping] = useState<string | null>(null);
  const [confirmationMapping, setConfirmationMapping] = useState<string | null>(null);
  const [mappingEnCours, setMappingEnCours] = useState(false);

  const chargerFile = useCallback(async () => {
    try {
      setFile(await fetchCelcatFile());
      setErreurFile(null);
    } catch (e) {
      setErreurFile(message(e, "serveur injoignable"));
    }
  }, []);

  const chargerSysteme = useCallback(async () => {
    try {
      setEtat(await fetchCelcatEtat());
      setErreurEtat(null);
    } catch (e) {
      setErreurEtat(message(e, "Erreur de chargement"));
    }
    // L'instantané ne doit pas faire échouer l'écran — mais son échec ne
    // doit pas non plus se lire « aucun relevé » : la barre d'état affirmait
    // « Celcat n'a pas encore été relu » pendant que le verdict disait
    // « relevé pris il y a 36 min » (constaté le 20/09/2026).
    try {
      setInstantane(await fetchCelcatInstantane());
      setErreurInstantane(null);
    } catch (e) {
      setErreurInstantane(message(e, "relevé illisible"));
    }
  }, []);

  const chargerMappings = useCallback(async (indice: number | null) => {
    // Ne bloque pas l'écran : sans cette liste, on perd le panneau des
    // blocages, pas le verdict.
    setMappings(await fetchCelcatMappings(indice).catch(() => null));
  }, []);

  const chargerJournal = useCallback(async () => {
    const [x, l] = await Promise.all([
      fetchCelcatExtras("ouvert").catch(() => ({ extras: [] as CelcatExtra[] })),
      fetchCelcatLogs(50).catch(() => ({ items: [] as CelcatLog[], cursor: null })),
    ]);
    setExtras(x.extras);
    setLogs(l.items);
  }, []);

  const chargerComparaison = useCallback(async (indice: number) => {
    try {
      setComparaison(await fetchCelcatComparaison(indice));
      setErreurComparaison(null);
    } catch (e) {
      setErreurComparaison(message(e, "Comparaison impossible"));
    }
  }, []);

  useEffect(() => {
    void chargerSysteme();
    void chargerFile();
    void chargerJournal();
    fetchAppState()
      .then((p) => {
        const rows = p.weekRows ?? [];
        setLignes(rows);
        const liste = semainesDuSolveur(rows);
        setSemaines(liste);
        // La semaine EN COURS, par le `weekIndex` de sa ligne et jamais par
        // sa position : les vacances creusent des trous dans `weekRows`.
        const ligneCourante = rows[indexSemaineCourante(rows)];
        const indiceCourant = ligneCourante?.weekIndex ?? null;
        setCourante(indiceCourant);
        setSemaine((actuelle) => {
          if (actuelle !== null) return actuelle;
          if (indiceCourant !== null) return indiceCourant;
          return liste[0]?.indice ?? 0;
        });
      })
      .catch(() => {
        // Sans calendrier, on retombe sur des numéros bruts plutôt que de
        // bloquer tout l'écran — et on le signale par le libellé même.
        setSemaines(Array.from({ length: 30 }, (_, i) => ({ indice: i, libelle: `Semaine ${i + 1} (dates indisponibles)` })));
        setSemaine((actuelle) => actuelle ?? 0);
      });
  }, [chargerSysteme, chargerFile, chargerJournal]);

  useEffect(() => {
    if (semaine === null) {
      setComparaison(null);
      return;
    }
    // On efface l'ancienne comparaison : la laisser affichée pendant le
    // chargement faisait lire les écarts d'une semaine sous le nom d'une autre.
    setComparaison(null);
    setErreurComparaison(null);
    void chargerComparaison(semaine);
    // Les blocages suivent la semaine regardée : « il faut afficher les
    // séances bloquées de la semaine uniquement » (20/09/2026).
    void chargerMappings(semaine);
  }, [semaine, chargerComparaison, chargerMappings]);

  const enAttente = file?.en_attente ?? 0;
  useEffect(() => {
    if (enAttente === 0) return;
    const minuteur = window.setTimeout(() => {
      void chargerFile();
      void chargerSysteme();
    }, cadence.sondageFileMs ?? SONDAGE_FILE_MS);
    return () => window.clearTimeout(minuteur);
  }, [file, enAttente, chargerFile, chargerSysteme, cadence.sondageFileMs]);

  const agirSurMapping = useCallback(
    async (action: () => Promise<CelcatMappings>, messageSucces: string) => {
      setMappingEnCours(true);
      setErreurMapping(null);
      setConfirmationMapping(null);
      try {
        setMappings(await action());
        // Confirmation en un mot : sans elle, un clic qui a marché ne se
        // distingue en rien d'un clic resté sans effet (Kyllian Bresson,
        // 25/09/2026 — « j'ai l'impression que le clic sur mapper ne
        // fonctionne pas »). Le blocage, lui, disparaît déjà de `mappings`
        // : `celcat_mappings()` ne le compte plus dès qu'une correspondance
        // existe pour sa clé, sans attendre le prochain passage du worker.
        setConfirmationMapping(messageSucces);
        // La correspondance prend effet au passage suivant du worker : on relit
        // le journal pour que les blocages réglés cessent d'être affichés.
        await chargerJournal();
      } catch (e) {
        setErreurMapping(message(e, "Correspondance impossible à enregistrer"));
      } finally {
        setMappingEnCours(false);
      }
    },
    [chargerJournal],
  );

  const boucle = useBoucleCelcat(semaine, {
    intervalleMs: cadence.intervalleMs,
    limiteWorkerMs: cadence.limiteWorkerMs,
    limiteReleveMs: cadence.limiteReleveMs,
    onVerifie: async () => {
      await Promise.all([
        semaine !== null ? chargerComparaison(semaine) : Promise.resolve(),
        chargerSysteme(),
        chargerFile(),
        chargerJournal(),
        chargerMappings(semaine),
      ]);
    },
  });

  if (erreurEtat && !etat) {
    return (
      <section className="view celcat">
        <p className="alerte" role="alert">
          Écran Celcat indisponible : {erreurEtat}
        </p>
      </section>
    );
  }

  if (!etat) {
    return (
      <section className="view celcat" aria-busy="true">
        <p className="celcat-sous-texte">Chargement de l’état de Celcat…</p>
      </section>
    );
  }

  const creationAutorisee = comparaison
    ? (etat.semaines_creation_autorisee ?? []).includes(comparaison.semaine_celcat)
    : false;

  return (
    <section className="view celcat">
      {erreurEtat ? (
        <p className="alerte" role="alert">
          État de Celcat non rafraîchi : {erreurEtat}
        </p>
      ) : null}

      <div className="page-outils celcat-barre">
        {semaineGlobale ? null : semaine !== null ? (
          <NavigationSemaine
            semaines={semaines}
            semaine={semaine}
            courante={courante}
            onSemaine={setSemaine}
            occupe={boucle.occupe}
          />
        ) : (
          <p className="celcat-sous-texte">Chargement du calendrier…</p>
        )}
        <StatutCelcat etat={etat} instantane={instantane} file={file} erreurInstantane={erreurInstantane} />
        {/* Tous les codes Celcat (cours, salles, enseignants, groupes) et leur
            origine vivent dans Référence (30/09/2026) : un lien, pas un
            second écran de saisie. */}
        <a className="btn btn--ghost btn--sm celcat-lien-codes" href="#vue=reference&onglet=codes-celcat">
          Codes Celcat →
        </a>
      </div>

      {semaineFermee ? (
        <section className="panel celcat-fermee" role="status">
          <h2>{ligneGlobale?.label ?? "Semaine"} : pas de cours</h2>
          <p className="celcat-sous-texte">
            Semaine fermée (vacances ou semaine bloquée) : rien à comparer avec Celcat. Choisissez une autre semaine
            dans la barre du haut.
          </p>
        </section>
      ) : semaine !== null ? (
        <VerdictCelcat
          donnees={comparaison}
          erreur={erreurComparaison}
          boucle={boucle.etat}
          occupe={boucle.occupe}
          enFile={file ? file.en_attente : null}
          onCorriger={() => void boucle.corriger(false)}
          onVerifier={() => void boucle.verifier()}
          onArreter={boucle.arreter}
        />
      ) : semaineGlobale ? (
        <p className="celcat-sous-texte">Chargement du calendrier…</p>
      ) : null}

      <div className="celcat-colonnes">
        <div className="celcat-principal">
          {comparaison ? <DetailComparaisonCelcat donnees={comparaison} /> : null}
          {comparaison ? (
            <SuppressionsCelcat donnees={comparaison} occupe={boucle.occupe} onSupprimer={() => void boucle.corriger(true)} />
          ) : null}
        </div>

        <aside className="celcat-lateral" aria-label="Envoi vers Celcat">
          <section className="panel celcat-en-route" aria-labelledby="celcat-en-route-titre">
            <h2 id="celcat-en-route-titre" className="celcat-panneau-titre">
              En route vers Celcat
            </h2>
            <EtatFileCelcat
              file={file}
              erreur={erreurFile}
              semaineCelcat={comparaison?.semaine_celcat ?? null}
              creationAutorisee={creationAutorisee}
              onAutoriserCreation={(autorisee) => {
                if (!comparaison) return;
                void (async () => {
                  try {
                    setEtat(await autoriserCreationSemaineCelcat(comparaison.semaine_celcat, autorisee));
                    await chargerFile();
                  } catch (e) {
                    setErreurFile(e instanceof Error ? e.message : "Autorisation impossible.");
                  }
                })();
              }}
            />
          </section>

          <BlocagesCelcat
            mappings={mappings}
            occupe={mappingEnCours}
            erreur={erreurMapping}
            confirmation={confirmationMapping}
            onMapper={(famille, cle, valeur) =>
              void agirSurMapping(
                () => definirMappingCelcat(famille, cle, valeur, semaine),
                `Correspondance enregistrée : ${cle} → ${valeur}.`,
              )
            }
            onOublier={(famille, cle) =>
              void agirSurMapping(
                () => oublierMappingCelcat(famille, cle, semaine),
                `Correspondance retirée : ${cle}.`,
              )
            }
          />
        </aside>
      </div>

      <JournalCelcat logs={logs} />

      <ReglagesCelcat
        etat={etat}
        setEtat={(e) => {
          setEtat(e);
          void chargerFile();
        }}
        file={file}
        extras={extras}
        setExtras={setExtras}
        semaines={semaines}
      />
    </section>
  );
}
