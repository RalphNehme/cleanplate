from app.queries import group_chains


def row(rid, score, chain_id=None, name="Place"):
    return {
        "id": rid,
        "name": name,
        "food_score": score,
        "chain_id": chain_id,
        "chain_name": "Greens Co" if chain_id else None,
    }


def test_chain_locations_collapse_into_one_entry_in_first_seen_order():
    rows = [
        row(1, 100, chain_id=7, name="Greens Co #1"),
        row(2, 90),
        row(3, 80, chain_id=7, name="Greens Co #2"),
        row(4, 95, chain_id=7, name="Greens Co #3"),
    ]
    out = group_chains(rows)
    assert [e["id"] for e in out] == [1, 2]
    chain = out[0]
    assert chain["name"] == "Greens Co"
    assert chain["locations"] == 3
    assert (chain["food_min"], chain["food_max"], chain["food_avg"]) == (80, 100, 90)
    assert out[1]["locations"] == 1


def test_grouping_respects_the_limit():
    rows = [row(i, 70) for i in range(50)]
    assert len(group_chains(rows, limit=30)) == 30
