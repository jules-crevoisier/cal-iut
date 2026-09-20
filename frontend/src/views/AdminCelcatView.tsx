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
 * L'écran se lit désormais de haut en bas :
 *
 *   1. l'état du système — écriture, worker, relevé — sans lequel rien ne part ;
 *   2. le VERDICT de la semaine en cours, et le geste qui corrige, suivi
 *      jusqu'à la vérification sur un relevé neuf ;
 *   3. les évènements en trop, seul geste resté humain ;
 *   4. ce qui est en route vers Celcat ;
 *   5. repliés : le détail séance par séance, l'activité, les réglages.
 *
 * Le style reste celui de la maison (`.orchestrator/architect-contract-celcat-ui.md`) :
 * mêmes panneaux, boutons, pastilles et jetons. Seule la clause « un seul
 * module React » est tombée, sa justification ne tenant plus.
 */
import { useCallback, useEffect, useState } from "react";

import {
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
import { VerdictCelcat, type SemaineChoisissable } from "../components/VerdictCelcat";
import { useBoucleCelcat } from "../hooks/useBoucleCelcat";
import { indexSemaineCourante } from "../utils/semaineCourante";

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
  const [file, setFile] = useState<CelcatFile | null>(null);
  const [erreurFile, setErreurFile] = useState<string | null>(null);
  const [extras, setExtras] = useState<CelcatExtra[]>([]);
  const [logs, setLogs] = useState<CelcatLog[]>([]);
  const [semaines, setSemaines] = useState<SemaineChoisissable[]>([]);
  // Indice INTERNE de la semaine comparée. `null` tant que le calendrier n'est
  // pas chargé : mieux vaut ne pas comparer que comparer la mauvaise. Le
  // défaut était `0`, la première semaine de l'année.
  const [semaine, setSemaine] = useState<number | null>(null);
  const [comparaison, setComparaison] = useState<CelcatComparaison | null>(null);
  const [erreurComparaison, setErreurComparaison] = useState<string | null>(null);
  const [mappings, setMappings] = useState<CelcatMappings | null>(null);
  const [erreurMapping, setErreurMapping] = useState<string | null>(null);
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
    // L'instantané ne doit pas faire échouer l'écran : sans relevé, le
    // verdict le dit lui-même.
    setInstantane(await fetchCelcatInstantane().catch(() => null));
  }, []);

  const chargerMappings = useCallback(async () => {
    // Ne bloque pas l'écran : sans cette liste, on perd le panneau des
    // blocages, pas le verdict.
    setMappings(await fetchCelcatMappings().catch(() => null));
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
    void chargerMappings();
    fetchAppState()
      .then((p) => {
        const rows = p.weekRows ?? [];
        const liste = semainesDuSolveur(rows);
        setSemaines(liste);
        setSemaine((actuelle) => {
          if (actuelle !== null) return actuelle;
          // La semaine EN COURS, par le `weekIndex` de sa ligne et jamais par
          // sa position : les vacances creusent des trous dans `weekRows`.
          const courante = rows[indexSemaineCourante(rows)];
          if (courante?.weekIndex != null) return courante.weekIndex;
          return liste[0]?.indice ?? 0;
        });
      })
      .catch(() => {
        // Sans calendrier, on retombe sur des numéros bruts plutôt que de
        // bloquer tout l'écran — et on le signale par le libellé même.
        setSemaines(Array.from({ length: 30 }, (_, i) => ({ indice: i, libelle: `Semaine ${i + 1} (dates indisponibles)` })));
        setSemaine((actuelle) => actuelle ?? 0);
      });
  }, [chargerSysteme, chargerFile, chargerJournal, chargerMappings]);

  useEffect(() => {
    if (semaine === null) return;
    // On efface l'ancienne comparaison : la laisser affichée pendant le
    // chargement faisait lire les écarts d'une semaine sous le nom d'une autre.
    setComparaison(null);
    setErreurComparaison(null);
    void chargerComparaison(semaine);
  }, [semaine, chargerComparaison]);

  const enAttente = file?.en_attente ?? 0;
  useEffect(() => {
    if (enAttente === 0) return;
    const minuteur = window.setTimeout(() => {
      void chargerFile();
      void chargerSysteme();
    }, cadence.sondageFileMs ?? SONDAGE_FILE_MS);
    return () => window.clearTimeout(minuteur);
  }, [file, enAttente, chargerFile, chargerSysteme, cadence.sondageFileMs]);

  const agirSurMapping = useCallback(async (action: () => Promise<CelcatMappings>) => {
    setMappingEnCours(true);
    setErreurMapping(null);
    try {
      setMappings(await action());
      // La correspondance prend effet au passage suivant du worker : on relit
      // le journal pour que les blocages réglés cessent d'être affichés.
      await chargerJournal();
    } catch (e) {
      setErreurMapping(message(e, "Correspondance impossible à enregistrer"));
    } finally {
      setMappingEnCours(false);
    }
  }, [chargerJournal]);

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
        chargerMappings(),
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

  return (
    <section className="view celcat">
      {erreurEtat ? (
        <p className="alerte" role="alert">
          État de Celcat non rafraîchi : {erreurEtat}
        </p>
      ) : null}

      <StatutCelcat etat={etat} instantane={instantane} file={file} />

      {semaine === null ? (
        <section className="panel celcat-verdict" aria-busy="true">
          <p className="celcat-sous-texte">Chargement du calendrier…</p>
        </section>
      ) : (
        <VerdictCelcat
          semaines={semaines}
          semaine={semaine}
          onSemaine={setSemaine}
          donnees={comparaison}
          erreur={erreurComparaison}
          boucle={boucle.etat}
          occupe={boucle.occupe}
          onCorriger={() => void boucle.corriger(false)}
          onVerifier={() => void boucle.verifier()}
          onArreter={boucle.arreter}
        />
      )}

      {comparaison ? (
        <SuppressionsCelcat donnees={comparaison} occupe={boucle.occupe} onSupprimer={() => void boucle.corriger(true)} />
      ) : null}

      <BlocagesCelcat
        mappings={mappings}
        occupe={mappingEnCours}
        erreur={erreurMapping}
        onMapper={(famille, cle, valeur) =>
          void agirSurMapping(() => definirMappingCelcat(famille, cle, valeur))
        }
        onOublier={(famille, cle) => void agirSurMapping(() => oublierMappingCelcat(famille, cle))}
      />

      <section className="panel celcat-en-route" aria-labelledby="celcat-en-route-titre">
        <h2 id="celcat-en-route-titre">En route vers Celcat</h2>
        <EtatFileCelcat file={file} erreur={erreurFile} />
      </section>

      {comparaison ? <DetailComparaisonCelcat donnees={comparaison} /> : null}

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
