/**
 * « Ajouter à mon agenda » — le lien d'abonnement .ics (flux qui se remet à
 * jour tout seul, retour utilisateur 28/08/2026), rendu utilisable par
 * quelqu'un qui ne sait pas ce qu'est un « lien d'abonnement ».
 *
 * Copier une URL puis chercher « ajouter un agenda par URL » dans les
 * réglages de son téléphone, c'est là que la plupart abandonnent. Le menu
 * propose donc aussi les deux raccourcis qui font le travail en un geste :
 *
 * - `webcal://` : l'iPhone, le Mac et Outlook ouvrent directement leur
 *   fenêtre d'abonnement ;
 * - Google Agenda : la page d'ajout par URL, déjà remplie.
 *
 * « Copier le lien » reste en tête : c'est le seul chemin universel.
 */

import { useEffect, useRef, useState } from "react";

import { copyToClipboard } from "../utils/clipboard";
import { Chevron } from "./NavSemaine";

import "./Planning.css";

interface MenuAgendaProps {
  /** URL https du flux .ics (cf. `utils/ics.ts::subscribeUrl`). */
  url: string;
  libelle?: string;
}

export function webcalDepuis(url: string): string {
  return url.replace(/^https?:\/\//, "webcal://");
}

export function googleAgendaDepuis(url: string): string {
  return `https://calendar.google.com/calendar/r?cid=${encodeURIComponent(webcalDepuis(url))}`;
}

export function MenuAgenda({ url, libelle = "Ajouter à mon agenda" }: MenuAgendaProps) {
  const [ouvert, setOuvert] = useState(false);
  const [copie, setCopie] = useState<"" | "ok" | "echec">("");
  const conteneur = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ouvert) return;
    const dehors = (e: MouseEvent) => {
      if (!conteneur.current?.contains(e.target as Node)) setOuvert(false);
    };
    const echap = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOuvert(false);
    };
    document.addEventListener("mousedown", dehors);
    document.addEventListener("keydown", echap);
    return () => {
      document.removeEventListener("mousedown", dehors);
      document.removeEventListener("keydown", echap);
    };
  }, [ouvert]);

  const copier = async () => {
    const ok = await copyToClipboard(url);
    setCopie(ok ? "ok" : "echec");
    window.setTimeout(() => setCopie(""), 1800);
  };

  return (
    <div className="menu" ref={conteneur}>
      <button
        type="button"
        className="btn btn--sm"
        aria-expanded={ouvert}
        aria-haspopup="menu"
        onClick={() => setOuvert((v) => !v)}
      >
        {libelle}
        <Chevron sens="bas" />
      </button>
      {ouvert && (
        <div className="menu-liste" role="menu">
          <button type="button" role="menuitem" onClick={() => void copier()}>
            {copie === "ok" ? "Lien copié ✓" : copie === "echec" ? "Copie impossible" : "Copier le lien d'abonnement"}
            <span>à coller dans n'importe quelle application d'agenda</span>
          </button>
          <a role="menuitem" href={webcalDepuis(url)} onClick={() => setOuvert(false)}>
            iPhone, Mac, Outlook
            <span>ouvre directement l'abonnement</span>
          </a>
          <a role="menuitem" href={googleAgendaDepuis(url)} target="_blank" rel="noopener noreferrer" onClick={() => setOuvert(false)}>
            Google Agenda
            <span>ajoute l'agenda à votre compte Google</span>
          </a>
          <p className="menu-note">L'agenda se met à jour tout seul quand le planning change.</p>
        </div>
      )}
    </div>
  );
}
