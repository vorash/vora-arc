import json
from pathlib import Path

import pytest

from vora_arc import model
from vora_arc.model import Pair, Task
from vora_arc.tasks import TaskFormatError, load_split, load_task, parse_task

DATA = Path(__file__).resolve().parents[1] / "data"
needs_data = pytest.mark.skipif(
    not (DATA / "arc1").is_dir() or not (DATA / "arc2").is_dir(),
    reason="ARC data not downloaded; run scripts/download_data.sh",
)


def valid_task() -> dict[str, object]:
    return {
        "train": [{"input": [[0, 1], [2, 3]], "output": [[3, 2], [1, 0]]}],
        "test": [{"input": [[4]], "output": [[5]]}],
    }


def test_parses_grids_into_tuples_and_keeps_test_outputs() -> None:
    assert parse_task("abc", valid_task()) == Task(
        id="abc",
        train=(Pair(input=((0, 1), (2, 3)), output=((3, 2), (1, 0))),),
        test=(model.TestCase(input=((4,),), output=((5,),)),),
    )


def test_test_case_without_output_is_allowed() -> None:
    # Hidden test sets ship inputs only; the loader must not demand an answer.
    raw = valid_task()
    raw["test"] = [{"input": [[4]]}]
    assert parse_task("abc", raw).test == (model.TestCase(input=((4,),), output=None),)


def test_unknown_top_level_keys_are_ignored() -> None:
    # Some ARC-AGI-2 files carry a "name" key next to train and test.
    raw = valid_task() | {"name": "x"}
    assert parse_task("abc", raw).id == "abc"


@pytest.mark.parametrize(
    ("where", "bad", "problem"),
    [
        ("train[0].output", [[1, 2], [3]], "row 1 has 1 cells, expected 2"),
        ("train[0].output", [[1, 10]], "cell [0][1] is 10"),
        ("train[0].output", [[1, -1]], "cell [0][1] is -1"),
        ("train[0].output", [[1, True]], "cell [0][1] is True"),
        ("train[0].output", [[1.0]], "cell [0][0] is 1.0"),
        ("train[0].output", [], "has 0 rows"),
        ("train[0].output", [[]], "row 0 has 0 cells"),
        ("train[0].output", [[0] * 31], "row 0 has 31 cells"),
        ("train[0].output", [[0]] * 31, "has 31 rows"),
        ("train[0].output", "[[0]]", "expected a list of rows, got str"),
        ("train[0].output", [[0], 5], "row 1 is int"),
    ],
)
def test_bad_grid_names_task_location_and_problem(where: str, bad: object, problem: str) -> None:
    raw = valid_task()
    raw["train"] = [{"input": [[0]], "output": bad}]
    with pytest.raises(TaskFormatError) as e:
        parse_task("t1", raw)
    assert str(e.value).startswith(f"task t1: {where}: {problem}")


def test_largest_legal_grid_is_accepted() -> None:
    raw = valid_task()
    raw["test"] = [{"input": [[9] * 30] * 30}]
    assert len(parse_task("t1", raw).test[0].input) == 30


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ([], "task t1: top level: expected an object, got list"),
        ({"test": [{"input": [[0]]}]}, "task t1: train: expected a non-empty list"),
        ({"train": [], "test": [{"input": [[0]]}]}, "task t1: train: expected a non-empty list"),
        ({"train": [{"input": [[0]]}], "test": [{"input": [[0]]}]}, "task t1: train[0]: missing output grid"),
        ({"train": [{"input": [[0]], "output": [[0]]}], "test": [{}]}, "task t1: test[0]: expected an object"),
    ],
)
def test_bad_structure_names_task_and_location(raw: object, message: str) -> None:
    with pytest.raises(TaskFormatError) as e:
        parse_task("t1", raw)
    assert str(e.value).startswith(message)


def test_load_task_uses_file_stem_as_id(tmp_path: Path) -> None:
    path = tmp_path / "0a1b2c3d.json"
    path.write_text(json.dumps(valid_task()))
    assert load_task(path).id == "0a1b2c3d"


def test_load_task_reports_bad_json_with_id(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{")
    with pytest.raises(TaskFormatError, match="task broken: not valid JSON"):
        load_task(path)


def test_load_split_sorts_by_id_and_rejects_empty_dir(tmp_path: Path) -> None:
    for task_id in ("bb", "aa"):
        (tmp_path / f"{task_id}.json").write_text(json.dumps(valid_task()))
    assert [t.id for t in load_split(tmp_path)] == ["aa", "bb"]
    with pytest.raises(TaskFormatError, match="no task files"):
        load_split(tmp_path / "missing")


@needs_data
@pytest.mark.parametrize(
    ("split", "count"),
    [
        ("arc1/training", 400),
        ("arc1/evaluation", 400),
        ("arc2/training", 1000),
        ("arc2/evaluation", 120),
    ],
)
def test_every_public_task_loads(split: str, count: int) -> None:
    # Exact counts catch a partial or wrong-commit download.
    tasks = load_split(DATA / split)
    assert len(tasks) == count
    assert all(t.train and t.test for t in tasks)
