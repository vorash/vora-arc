"""Which answers a task submits. A wrong order here silently changes the accuracy."""

from __future__ import annotations

from vora_arc import model
from vora_arc.model import Grid, GridResult, GridStatus, Pair, Task
from vora_arc.vote import Ballot, ballot, vote

A: Grid = ((1,),)
B: Grid = ((2,),)
C: Grid = ((3,),)
TASK = Task(id="t", train=(Pair(((0,),), ((0,),)),), test=(model.TestCase(((9,),), A),))


def votes_for(output: Grid, count: int, length: int = 10) -> list[Ballot]:
    return [Ballot((output,), length)] * count


def test_the_output_with_the_most_votes_ranks_first() -> None:
    answers = vote(TASK, votes_for(B, 1) + votes_for(A, 3) + votes_for(C, 2))
    assert [(a.rank, a.outputs, a.votes) for a in answers] == [(1, (A,), 3), (2, (C,), 2)]


def test_a_tied_count_goes_to_the_shortest_program_in_the_group() -> None:
    long_only = [Ballot((A,), 100), Ballot((A,), 100)]
    has_short = [Ballot((B,), 200), Ballot((B,), 50)]
    answers = vote(TASK, long_only + has_short)
    assert [a.outputs for a in answers] == [(B,), (A,)]


def test_count_outranks_length() -> None:
    answers = vote(TASK, [Ballot((A,), 1)] + [Ballot((B,), 500)] * 2)
    assert answers[0].outputs == (B,)


def test_at_most_two_distinct_answers() -> None:
    answers = vote(TASK, votes_for(A, 1) + votes_for(B, 1) + votes_for(C, 1))
    assert len(answers) == 2
    assert answers[0].outputs != answers[1].outputs


def test_identical_outputs_from_different_programs_group_together() -> None:
    answers = vote(TASK, [Ballot((A,), 10), Ballot((A,), 20)])
    assert [(a.votes, a.outputs) for a in answers] == [(2, (A,))]


def test_either_attempt_can_be_the_correct_one() -> None:
    first, second = vote(TASK, votes_for(B, 2) + votes_for(A, 1))
    assert (first.correct, second.correct) == (False, True)


def test_a_task_with_several_test_inputs_is_answered_as_a_whole() -> None:
    task = Task(id="t", train=TASK.train, test=(model.TestCase(((8,),), A), model.TestCase(((9,),), B)))
    half_right = [Ballot((A, C), 10)] * 2
    all_right = [Ballot((A, B), 10)]
    first, second = vote(task, half_right + all_right)
    assert (first.outputs, first.votes, first.correct) == ((A, C), 2, False)
    assert (second.outputs, second.votes, second.correct) == ((A, B), 1, True)


def test_hidden_test_outputs_leave_correctness_unknown() -> None:
    task = Task(id="t", train=TASK.train, test=(model.TestCase(((9,),), None),))
    assert vote(task, votes_for(A, 1))[0].correct is None


def test_no_ballots_means_no_answers() -> None:
    assert vote(TASK, []) == ()


def grid(index: int, status: GridStatus, output: Grid | None, is_test: bool = True) -> GridResult:
    return GridResult(index, is_test, status, output, None, 1)


def test_a_ballot_lists_test_outputs_in_input_order() -> None:
    item = ballot("p", [grid(2, GridStatus.OK, B), grid(0, GridStatus.OK, C, is_test=False), grid(1, GridStatus.OK, A)])
    assert item == Ballot((A, B), 1)


def test_a_passed_program_whose_test_input_crashed_cannot_vote() -> None:
    assert ballot("p", [grid(1, GridStatus.OK, A), grid(2, GridStatus.ERROR, None)]) is None


def test_a_forged_invalid_test_output_cannot_vote() -> None:
    assert ballot("p", [grid(1, GridStatus.OK, ((11,),))]) is None
    assert ballot("p", [grid(1, GridStatus.OK, ((1, 2), (3,)))]) is None
