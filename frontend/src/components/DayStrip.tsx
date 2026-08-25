import { DAY_LABELS } from "../utils/slots";

interface DayStripProps {
  selected: number;
  onSelect: (day: number) => void;
}

/** Barre de sélection de jour — affichée uniquement en lecture mobile (écran étroit). */
export function DayStrip({ selected, onSelect }: DayStripProps) {
  return (
    <div className="daystrip">
      {DAY_LABELS.map((label, d) => (
        <button
          key={label}
          type="button"
          className={d === selected ? "active" : ""}
          onClick={() => onSelect(d)}
        >
          <span className="dfull">{label}</span>
          <span className="dshort">{label.slice(0, 3)}</span>
        </button>
      ))}
    </div>
  );
}

export function todayIndex(): number {
  const wd = new Date().getDay(); // 0 = dimanche
  return wd >= 1 && wd <= 5 ? wd - 1 : 0;
}
