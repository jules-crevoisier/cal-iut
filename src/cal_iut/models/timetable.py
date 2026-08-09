"""Grille horaire et créneaux."""

from enum import IntEnum


class WeekDay(IntEnum):
    """Jours de la semaine (lundi = 0)."""

    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4


class TimeSlot(IntEnum):
    """Créneaux de 1h30 (pause déjeuner 12h30-14h00 exclue)."""

    SLOT_08_0930 = 0  # 8h00 - 9h30
    SLOT_0930_11 = 1  # 9h30 - 11h00
    SLOT_11_1230 = 2  # 11h00 - 12h30
    SLOT_14_1530 = 3  # 14h00 - 15h30
    SLOT_1530_17 = 4  # 15h30 - 17h00
    SLOT_17_1830 = 5  # 17h00 - 18h30

    @property
    def label(self) -> str:
        labels = (
            "8h-9h30",
            "9h30-11h",
            "11h-12h30",
            "14h-15h30",
            "15h30-17h",
            "17h-18h30",
        )
        return labels[self.value]

    @classmethod
    def count(cls) -> int:
        return len(cls)


SLOTS_PER_DAY = TimeSlot.count()
DAYS_PER_WEEK = len(WeekDay)
