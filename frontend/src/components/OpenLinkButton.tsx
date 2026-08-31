/**
 * Icône « ouvrir dans un nouvel onglet » — à coller à côté d'un CopyButton
 * de lien perso (annuaire, liste profs), pas pour un flux .ics.
 */

interface OpenLinkButtonProps {
  href: string;
  label?: string;
}

export function OpenLinkButton({ href, label = "Ouvrir dans un nouvel onglet" }: OpenLinkButtonProps) {
  return (
    <a
      className="btn btn--ghost btn--sm btn--icon"
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      title={label}
      aria-label={label}
    >
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <path
          d="M6.2 3.2H3.6A1.4 1.4 0 0 0 2.2 4.6v7.8A1.4 1.4 0 0 0 3.6 13.8h7.8a1.4 1.4 0 0 0 1.4-1.4V9.8M9.2 2.2h4.6V6.8M8.4 7.6l5.4-5.4"
          stroke="currentColor"
          strokeWidth="1.7"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </a>
  );
}
