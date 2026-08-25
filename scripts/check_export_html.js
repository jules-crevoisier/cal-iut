/**
 * Contrôle d'exécution réelle de l'export HTML autonome.
 *
 * Pourquoi un contrôle séparé : les tests Python de `tests/test_html_export.py`
 * cherchent des chaînes dans le HTML produit. Ils ne peuvent pas voir qu'une
 * erreur JavaScript au chargement casse la page — c'est exactement ce qui est
 * arrivé le 10/08/2026 (`ReferenceError: Cannot access 'DATE_FMT' before
 * initialization`, un `const` lu avant sa ligne de déclaration) : le HTML
 * contenait bien tout ce qu'on cherchait, et pourtant AUCUNE vue ne s'affichait.
 *
 * Ce script charge la page dans un vrai DOM (jsdom), exécute son script, et
 * échoue si la moindre erreur est levée — pour chacun des liens que l'on
 * distribue réellement.
 *
 * Usage :
 *   node scripts/check_export_html.js <fichier.html>
 *
 * Dépend de `jsdom`, non listé dans le projet (outil de développement) :
 *   npm install --no-save jsdom
 */

const fs = require("fs");
const path = require("path");

let JSDOM;
try {
  ({ JSDOM } = require("jsdom"));
} catch (err) {
  console.error("jsdom absent — `npm install --no-save jsdom` puis relancer.");
  process.exit(2);
}

const file = process.argv[2];
if (!file || !fs.existsSync(file)) {
  console.error(`Usage : node ${path.basename(__filename)} <fichier.html>`);
  process.exit(2);
}
const html = fs.readFileSync(file, "utf8");

/**
 * Charge la page sur un fragment donné et renvoie {errors, doc}.
 *
 * `narrow` simule un écran étroit : jsdom n'implémente pas `matchMedia`, on le
 * fournit donc nous-mêmes pour pouvoir vérifier LES DEUX affichages (grille 5
 * jours et lecture jour par jour) — sinon seul le cas bureau serait testé.
 */
function load(hash, narrow = false) {
  const errors = [];
  const dom = new JSDOM(html, {
    runScripts: "dangerously",
    url: "https://example.test/planning.html" + hash,
    beforeParse(w) {
      w.addEventListener("error", (e) =>
        errors.push((e.error && e.error.stack) || e.message)
      );
      const orig = w.console.error;
      w.console.error = (...a) => {
        errors.push("console.error: " + a.join(" "));
        orig.apply(w.console, a);
      };
      // `window.print` n'existe pas dans jsdom et n'est pas le sujet ici.
      w.print = () => {};
      w.matchMedia = (query) => ({
        media: query,
        matches: narrow && /max-width/.test(query),
        addEventListener() {},
        removeEventListener() {},
      });
    },
  });
  return { errors, doc: dom.window.document, dom };
}

const cases = [
  {
    hash: "",
    narrow: true,
    label: "lecture jour par jour (écran étroit)",
    check(doc) {
      // Retour utilisateur 10/08/2026 : sur téléphone, une semaine se lit jour
      // par jour. La grille ne doit plus afficher que la colonne du jour choisi,
      // et la barre de jours doit être présente pour en changer.
      const strip = doc.querySelector(".daystrip [data-mday]");
      if (!strip) return "barre de jours absente";
      const headers = doc.querySelectorAll("#semaineCalendarTable thead th");
      if (headers.length !== 2) return `${headers.length - 1} colonne(s) de jour au lieu d'une`;
      return null;
    },
  },
  {
    hash: "",
    label: "ouverture normale",
    check(doc) {
      const active = doc.querySelector(".tabpanel.active");
      if (!active) return "aucun onglet actif";
      if (!doc.querySelectorAll("#teacherLinksTable tbody tr").length)
        return "annuaire des liens enseignants vide";
      // Affichage large : les 5 jours + la colonne des horaires.
      const headers = doc.querySelectorAll("#semaineCalendarTable thead th");
      if (headers.length !== 6) return `${headers.length - 1} colonne(s) de jour au lieu de 5`;
      return null;
    },
  },
  {
    hash: "#vue=prof",
    label: "lien vers la vue Enseignant",
    check(doc) {
      const active = doc.querySelector(".tabpanel.active");
      return active && active.id === "tab-prof" ? null : `onglet actif = ${active && active.id}`;
    },
  },
  {
    hash: "#vue=reference",
    label: "lien vers la Référence",
    check(doc) {
      const active = doc.querySelector(".tabpanel.active");
      return active && active.id === "tab-reference" ? null : `onglet actif = ${active && active.id}`;
    },
  },
  {
    hash: "",
    label: "panneau « à traiter »",
    check(doc) {
      if (!doc.getElementById("todoList")) return "panneau absent";
      if (!doc.getElementById("todoCount")) return "compteur absent";
      return null;
    },
  },
  {
    hash: "",
    label: "recherche globale (Ctrl+K)",
    check(doc) {
      const overlay = doc.getElementById("searchOverlay");
      if (!overlay) return "overlay de recherche absent";
      if (overlay.hidden === false) return "overlay ouvert par défaut";
      if (!doc.getElementById("searchInput")) return "champ de recherche absent";
      return null;
    },
  },
];

// Les liens PERSONNELS (enseignant, groupe) : les cas qui comptent le plus,
// puisqu'ils partent vers des destinataires externes. Les identifiants sont
// repris du fichier lui-même pour ne dépendre d'aucune valeur codée en dur.
{
  const { doc } = load("");

  const teacher = doc.querySelector("#teacherLinksTable [data-ics]");
  if (teacher) {
    const code = teacher.dataset.ics;
    cases.push({
      hash: `#vue=prof&prof=${code}&mode=prof`,
      label: `lien personnel enseignant (${code})`,
      check(d) {
        if (!d.body.classList.contains("teacher-mode")) return "mode lecture seule non appliqué";
        const tabs = [...d.querySelectorAll(".tabbtn")];
        if (tabs.length !== 1 || tabs[0].dataset.tab !== "prof")
          return `onglets restants : ${tabs.map((t) => t.dataset.tab).join(",") || "(aucun)"}`;
        const agenda = d.getElementById("teacherAgenda");
        if (!agenda || !agenda.textContent.trim()) return "agenda du semestre vide";
        return null;
      },
    });
  }

  const group = doc.querySelector("#groupLinksTable [data-ics]");
  if (group) {
    const gid = group.dataset.ics;
    cases.push({
      hash: `#vue=groupe&groupe=${gid}&mode=groupe`,
      label: `lien groupe étudiant (${gid})`,
      check(d) {
        if (!d.body.classList.contains("teacher-mode")) return "mode lecture seule non appliqué";
        const tabs = [...d.querySelectorAll(".tabbtn")];
        if (tabs.length !== 1 || tabs[0].dataset.tab !== "groupe")
          return `onglets restants : ${tabs.map((t) => t.dataset.tab).join(",") || "(aucun)"}`;
        return null;
      },
    });
  }

  // Le lien copié doit être un vrai lien absolu, pas un trigramme : régression
  // réelle, la cellule ayant porté les deux formes au fil des versions.
  const copy = doc.querySelector("#teacherLinksTable [data-copy]");
  if (copy && !/^https?:\/\/.+#.*prof=/.test(copy.dataset.copy)) {
    console.error(`✗ le bouton « copier le lien » ne contient pas une URL : ${copy.dataset.copy}`);
    process.exitCode = 1;
  }
}

let failed = 0;
for (const c of cases) {
  const { errors, doc, dom } = load(c.hash, !!c.narrow);
  const problem = errors.length ? errors[0] : c.check(doc);
  if (problem) {
    failed++;
    console.error(`✗ ${c.label} (${c.hash || "sans fragment"})\n    ${problem}`);
  } else {
    console.log(`✓ ${c.label} (${c.hash || "sans fragment"})`);
  }
  dom.window.close();
}

process.exit(failed ? 1 : 0);
