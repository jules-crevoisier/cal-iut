import { useState } from "react";
import { copyToClipboard } from "../utils/clipboard";

interface ShareBarProps {
  onCopyLink: () => string;
  onDownloadIcs: () => void;
  extra?: React.ReactNode;
}

/** Barre "Copier son lien / Agenda .ics / Imprimer", commune aux vues Groupe et Enseignant. */
export function ShareBar({ onCopyLink, onDownloadIcs, extra }: ShareBarProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    const ok = await copyToClipboard(onCopyLink());
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    }
  };

  return (
    <div className="sharebar no-print">
      <button type="button" className="btn btn--ghost btn--sm" onClick={handleCopy}>
        {copied ? "Copié ✓" : "Copier son lien"}
      </button>
      <button type="button" className="btn btn--ghost btn--sm" onClick={onDownloadIcs}>
        Agenda .ics
      </button>
      <button type="button" className="btn btn--ghost btn--sm" onClick={() => window.print()}>
        Imprimer
      </button>
      {extra}
    </div>
  );
}
