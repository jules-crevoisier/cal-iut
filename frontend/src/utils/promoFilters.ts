/**
 * Filtres année / parcours pour la grille Vue Promo.
 */
export type FiltreTout = "Tout";

export function anneeDepuisParcours(parcours: string): string | null {
  const m = /^BUT(\d)/i.exec(parcours);
  return m ? `BUT${m[1]}` : null;
}

export function listerAnnees(parcoursList: string[]): string[] {
  const set = new Set<string>();
  for (const pc of parcoursList) {
    const a = anneeDepuisParcours(pc);
    if (a) set.add(a);
  }
  return [...set].sort((a, b) => a.localeCompare(b, "fr"));
}

export function filtrerParcours(
  parcoursList: string[],
  annee: string | FiltreTout,
  parcours: string | FiltreTout,
): string[] {
  let liste = [...new Set(parcoursList)].sort((a, b) => a.localeCompare(b, "fr"));
  if (annee !== "Tout") {
    liste = liste.filter((pc) => anneeDepuisParcours(pc) === annee);
  }
  if (parcours !== "Tout") {
    liste = liste.filter((pc) => pc === parcours);
  }
  return liste;
}

export function parcoursPourSelect(
  parcoursList: string[],
  annee: string | FiltreTout,
): string[] {
  return filtrerParcours(parcoursList, annee, "Tout");
}
