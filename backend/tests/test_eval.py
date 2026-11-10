"""The exam set must stay consistent with the tiering policy, and its checkers must work."""

from eval.run_eval import invented_precedents, load_cases, offline_case, summarise


def test_exam_set_has_enough_labelled_cases():
    cases = load_cases()
    assert 15 <= len(cases) <= 25
    assert len({c["id"] for c in cases}) == len(cases)
    for c in cases:
        assert "expected" in c and "snapshot" in c and "relevant_precedents" in c


def test_offline_exam_set_passes():
    # Regression gate: a threshold or retrieval change that breaks a labelled case fails here.
    summary = summarise([offline_case(c) for c in load_cases()])
    assert all(s["rate"] == 1.0 for s in summary.values()), summary


def test_invented_precedent_is_caught():
    text = "During the 2021 Yantian shutdown, terminals added night shifts."
    assert invented_precedents(text, "Antwerp", {"la-long-beach-2021"}) == ["yantian-2021"]


def test_retrieved_precedent_is_allowed():
    text = "During the 2021 Los Angeles backlog, truckers who pre-booked slots did better."
    assert invented_precedents(text, "Antwerp", {"la-long-beach-2021"}) == []


def test_alternative_port_is_not_a_precedent():
    text = "Consider diverting calls to Rotterdam or Zeebrugge if the queue keeps growing."
    assert invented_precedents(text, "Antwerp", {"la-long-beach-2021"}) == []


def test_number_written_as_word_counts_as_cited():
    from eval.run_eval import _cites_number
    assert _cites_number("هناك سفينة واحدة فقط في الانتظار", {"1"})
    assert _cites_number("Only one ship is waiting.", {"1"})
    assert not _cites_number("Traffic is light.", {"1", "2"})
