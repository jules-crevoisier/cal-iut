export interface CsvRow {
  type: string;
  label: string;
  code: string;
  mail: string;
  count: number;
  hours: number;
  link: string;
}

/** Annuaire enseignants + groupes en CSV, BOM UTF-8 (sans lui Excel lit le
 * fichier en ANSI et casse les accents) — portage direct du bouton
 * équivalent de la page HTML/JS historique. */
export function downloadDirectoryCsv(rows: CsvRow[]): void {
  const esc = (v: unknown) => `"${String(v).replace(/"/g, '""')}"`;
  const lines = [["Type", "Nom", "Code", "Mail", "Seances", "Heures", "Lien"].map(esc).join(";")];
  for (const r of rows) {
    lines.push([r.type, r.label, r.code, r.mail, r.count, r.hours.toFixed(1), r.link].map(esc).join(";"));
  }
  const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "annuaire-plannings.csv";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
