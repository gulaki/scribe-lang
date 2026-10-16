"""Compile to C, build with a real C compiler, run, and compare stdout.

These tests skip themselves when no C compiler is available.
"""
import pytest

from conftest import EXAMPLES


@pytest.mark.parametrize("stdin, expected", [
    ("5\n", "positive\n"),
    ("-3\n", "negative\n"),
    ("0\n", "zero\n"),
])
def test_if_elif_else_runs_exactly_one_branch(run_scribe, stdin, expected):
    program = '''\
input x
if x > 0 {
    print "positive"
} elif x < 0 {
    print "negative"
} else {
    print "zero"
}
'''
    assert run_scribe(program, stdin) == expected


def test_if_without_else_can_skip_everything(run_scribe):
    assert run_scribe('if 1 > 2 {\n    print "no"\n}\nprint "done"\n') == "done\n"


def test_elif_condition_is_only_evaluated_when_needed(run_scribe):
    program = 'x = 1\nif x == 1 {\n    print "a"\n} elif x == 1 {\n    print "b"\n}\n'
    assert run_scribe(program) == "a\n"


def test_while_body_variable_is_fresh_on_every_iteration(run_scribe):
    program = '''\
i = 0
while i < 3 {
    count = 0
    count = count + 1
    print count
    i = i + 1
}
'''
    assert run_scribe(program) == "1.00\n1.00\n1.00\n"


def test_inner_block_updates_outer_variable(run_scribe):
    program = '''\
total = 0
i = 1
while i <= 4 {
    if i > 2 {
        total = total + i
    }
    i = i + 1
}
print total
'''
    assert run_scribe(program) == "7.00\n"


def test_sibling_blocks_and_a_later_program_level_variable_are_independent(run_scribe):
    program = '''\
x = 1
if x > 0 {
    t = 10
    print t
} else {
    t = 20
    print t
}
t = 5
print t
'''
    assert run_scribe(program) == "10.00\n5.00\n"


def test_block_variable_that_shares_a_name_with_a_later_global_does_not_leak(run_scribe):
    program = '''\
if 1 > 0 {
    v = 7
    print v
}
v = 1
print v
'''
    assert run_scribe(program) == "7.00\n1.00\n"


def test_standalone_block_scope(run_scribe):
    program = 'x = 1\n{\n    x = x + 1\n    y = 10\n    print y\n}\nprint x\n'
    assert run_scribe(program) == "10.00\n2.00\n"


def test_goto_out_of_a_nested_block(run_scribe):
    program = '''\
i = 1
input n
label loop
print i
i = i + 1
if i <= n {
    goto loop
}
'''
    assert run_scribe(program, "3\n") == "1.00\n2.00\n3.00\n"


def test_label_at_the_end_of_a_block_is_valid_strict_c(run_scribe):
    program = '''\
x = 1
if x > 0 {
    goto done
    print "skipped"
    label done
}
print "after"
'''
    assert run_scribe(program) == "after\n"


def test_goto_inside_a_block_never_skips_a_declaration(run_scribe):
    # `a` is declared at the top of the block, so jumping over its first
    # assignment leaves it at 0 rather than uninitialised.
    program = '{\n    goto skip\n    a = 7\n    label skip\n    print a\n}\n'
    assert run_scribe(program) == "0.00\n"


def test_input_into_a_block_variable(run_scribe):
    program = '{\n    input n\n    print n * 2\n}\n'
    assert run_scribe(program, "21\n") == "42.00\n"


def test_deeply_nested_blocks(run_scribe):
    program = '''\
a = 1
{
    b = a + 1
    {
        c = b + 1
        {
            d = c + 1
            print d
        }
    }
}
'''
    assert run_scribe(program) == "4.00\n"


EXAMPLE_RUNS = {
    "factorial": ("5\n", "Enter number to calculate factorial:\n\nFactorial = \n120.00\n"),
    "fibonacci": ("6\n", "How many fibonacci numbers do you want?\n\n0.00\n1.00\n1.00\n2.00\n3.00\n5.00\n"),
    "loop_goto": ("3\n", "Enter number: \n1.00\n2.00\n3.00\n"),
    "classify": ("85\n", "Enter a score from 0 to 100:\ngrade B\n"),
    "gcd": ("48\n18\n", "Enter two positive whole numbers:\ngcd =\n6.00\n"),
    "scopes": ("", "10.00\n2.00\n0.00\n1.00\n4.00\n"),
    "nested_loops": ("", "6.00\n12.00\n18.00\n"),
    "primes": ("30\n", "Print primes up to:\n" + "".join(f"{p}.00\n" for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29))),
    "newton_sqrt": ("144\n", "Square root of (a number >= 0):\n12.00\n"),
    "sum_avg": ("3\n1\n2\n6\n", "How many numbers?\n" + "\nEnter number:\n" * 3 + "Sum =\n9.00\nAverage =\n3.00\n"),
}


@pytest.mark.parametrize("name", EXAMPLE_RUNS)
def test_example_program_output(run_scribe, name):
    stdin, expected = EXAMPLE_RUNS[name]
    source = (EXAMPLES / f"{name}.scribe").read_text(encoding="utf-8")
    assert run_scribe(source, stdin) == expected


@pytest.mark.parametrize("stdin, expected", [
    ("95\n", "grade A"), ("90\n", "grade A"), ("89\n", "grade B"),
    ("70\n", "grade C"), ("69\n", "grade F"), ("0\n", "grade F"),
])
def test_classify_example_boundaries(run_scribe, stdin, expected):
    source = (EXAMPLES / "classify.scribe").read_text(encoding="utf-8")
    assert run_scribe(source, stdin).splitlines()[-1] == expected


def test_every_example_has_a_recorded_run():
    on_disk = {path.stem for path in EXAMPLES.glob("*.scribe")}
    assert on_disk == set(EXAMPLE_RUNS), "add new examples to EXAMPLE_RUNS"
