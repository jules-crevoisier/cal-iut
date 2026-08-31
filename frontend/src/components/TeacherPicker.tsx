import { useMemo, useState } from "react";

interface TeacherPickerProps {
  selected: string[];
  labels: Record<string, string>;
  onChange: (codes: string[]) => void;
}

/** Multi-sélection d'enseignants avec champ de recherche — le catalogue
 *  dépasse la dizaine de codes, un `<select>` nu n'y suffit pas. */
export function TeacherPicker({ selected, labels, onChange }: TeacherPickerProps) {
  const [query, setQuery] = useState("");
  const [ouvert, setOuvert] = useState(false);

  const options = useMemo(() => {
    const q = query.trim().toLowerCase();
    return Object.entries(labels)
      .filter(([code]) => !selected.includes(code))
      .filter(([code, nom]) => {
        if (!q) return true;
        return code.toLowerCase().includes(q) || nom.toLowerCase().includes(q);
      })
      .sort((a, b) => a[1].localeCompare(b[1], "fr"))
      .slice(0, 20);
  }, [labels, query, selected]);

  const ajouter = (code: string) => {
    if (selected.includes(code)) return;
    onChange([...selected, code]);
    setQuery("");
    setOuvert(false);
  };

  const retirer = (code: string) => {
    onChange(selected.filter((c) => c !== code));
  };

  return (
    <div className="teacher-picker">
      <div className="teacher-picker-chips">
        {selected.length === 0 && <span className="muted small">Aucun enseignant</span>}
        {selected.map((code) => (
          <span key={code} className="teacher-picker-chip">
            {labels[code] ?? code}
            <button type="button" aria-label={`Retirer ${labels[code] ?? code}`} onClick={() => retirer(code)}>
              ×
            </button>
          </span>
        ))}
      </div>
      <div className="teacher-picker-recherche">
        <input
          role="combobox"
          aria-label="Rechercher un enseignant"
          aria-expanded={ouvert}
          aria-controls="teacher-picker-list"
          aria-autocomplete="list"
          placeholder="Rechercher un enseignant…"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOuvert(true);
          }}
          onFocus={() => setOuvert(true)}
          onBlur={() => {
            window.setTimeout(() => setOuvert(false), 120);
          }}
        />
        {ouvert && (
          <ul id="teacher-picker-list" className="teacher-picker-liste" role="listbox">
            {options.length === 0 && (
              <li className="teacher-picker-vide muted small">Aucun enseignant</li>
            )}
            {options.map(([code, nom]) => (
              <li
                key={code}
                role="option"
                aria-selected="false"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => ajouter(code)}
              >
                {nom} ({code})
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
