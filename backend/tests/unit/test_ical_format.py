from app.services.ical import escape_text, fold


def unfold(text: str) -> str:
    return text.replace("\r\n ", "")


def test_special_characters_are_escaped() -> None:
    assert escape_text("Аренда; офис, СПб\\Москва\nстрока") == "Аренда\\; офис\\, СПб\\\\Москва\\nстрока"


def test_short_line_is_left_alone() -> None:
    assert fold("SUMMARY:Аренда") == "SUMMARY:Аренда"


def test_long_cyrillic_line_is_folded_by_bytes_without_breaking_letters() -> None:
    line = "DESCRIPTION:" + "Бухгалтерское и налоговое сопровождение — ежемесячный акт " * 4

    folded = fold(line)

    assert unfold(folded) == line
    for part in folded.split("\r\n"):
        assert len(part.encode()) <= 75  # кириллица — 2 байта, строка режется по символам
        part.encode().decode()  # ни одна буква не разорвана
    assert all(p.startswith(" ") for p in folded.split("\r\n")[1:])
