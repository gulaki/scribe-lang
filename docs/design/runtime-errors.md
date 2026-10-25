# Runtime errors and tracebacks (draft specification)

Status: **draft 2, proposed.** The decisions made so far are in
[section 8](#8-decisions). Nothing on this page is implemented yet
except the existing traps, which stop the program with `abort()` (see
[errors.md](../errors.md#runtime-errors)). This page replaces that with
errors that propagate to `main` and print a traceback. Functions are
specified in [functions.md](functions.md).

## 1. Three kinds of error

| Kind | Found by | Codes | Examples |
|---|---|---|---|
| Syntax error | the parser | `E01xx` | `if x > {`, a missing `}` |
| Compile error | semantic analysis | `E02xx` ... `E06xx` (later `E07xx` for functions) | an undeclared name, a type mismatch, `2 ** -1` |
| Runtime error | the running program | `R0xxx` (new) | integer overflow, division by zero, a negative exponent |

Warnings (`W0xxx`) are not errors. The first, W0001, marks the deprecated
`goto` and `label`; unreachable code will be W0002 (functions.md, "Exit
analysis").

Runtime errors get stable codes like compile errors, so tests, scripts and
AI agents can rely on them.

| Code | Name | Error type (for `except`) | Message (today's text) |
|---|---|---|---|
| R0001 | integer-overflow | `OverflowError` | integer overflow |
| R0002 | division-by-zero | `ZeroDivisionError` | division by zero |
| R0003 | value-out-of-range | `ConversionError` | value out of range for i64 |
| R0004 | negative-exponent | `NegativeExponentError` | negative exponent |
| R0005 | recursion-limit | `RecursionError` | recursion limit reached (new, with functions) |
| R01xx | raised errors | `ValueError`, ... | `raise`, later also I/O and parse errors from the standard library |

The error types of the checks (R00xx) use Python's names where Python has the
same error, so they read as Python programmers expect.

## 2. Model: every runtime error propagates

Today a failed check calls `scribe_trap`, which prints one line and calls
`abort()`. With functions, that loses the call stack, skips any cleanup, and
gives the exit status of a crash.

**Proposal.** A runtime error, whether it comes from a check or from `raise`,
**returns** from the current function to its caller, which records where the
call was made and returns in turn, up to `main`. `main` then prints the
traceback and exits with status 1. Errors pass through ordinary C
return values ("kernel style"), with no `setjmp`/`longjmp` and no C++
exceptions.

Why propagate the checks too, not only `raise`:

- **One mechanism.** A single kind of traceback for every runtime error, in
  text and in JSON.
- **Cleanup runs.** Once there are owned values (memory-model.md) and
  `finally`, every exit edge must run cleanups, including the error edge.
  `abort()` runs none.
- **Embedded targets** get a normal return from `main` instead of an abort.
- **`try` stays possible** for any error later, even if v1 doesn't allow
  catching checks (section 7).

The cost is small. Every check already ends in a branch that is almost never
taken; that branch now leads to a `return` instead of to `abort()`. The
success path is unchanged: no allocation, no bookkeeping, and the same
number of compares.

## 3. The C calling convention

Every Scribe function returns `scribe_err`. The result, if there is one, is
written through a last pointer parameter.

```text
fn mean(i64: total, i64: count) -> i64
```

```c
typedef int32_t scribe_err;   /* 0 means success */

static scribe_err f_mean__i64_i64(int64_t v_total, int64_t v_count, int64_t *r_result);
```

- `scribe_err` is a plain integer, never a struct: it is returned in a
  register and tested with one compare. Everything else about the error goes
  in the **error record** (section 4), so success costs nothing and no
  allocation is ever needed. That matters because a future "out of memory"
  error must still be reportable.
- Parameters use the C type of their Scribe type (`int64_t`, `double`, ...),
  never `int` or `long`: `long` is 32 bits on Windows.
- A function with no return type has no result parameter.
- The result is written only on success; on failure `*r_result` is not
  touched. The caller's temporary keeps its starting zero, so no value ever
  depends on uninitialised memory.

A call `a = mean(t, n)` becomes:

```c
if (f_mean__i64_i64(v_t, v_n, &t_1) != 0) {
    scribe_trace(7);           /* site 7: this call, for the traceback */
    goto fail;
}
v_a = t_1;
```

`fail` is the function's error exit. It runs the cleanups that are live
(none until there are heap values) and does `return 1;`. In `main`, it
prints the traceback and returns 1.

The checked helpers change in the same way. They return a status and write
their result through a pointer:

```c
static scribe_err scribe_add_i64(int64_t a, int64_t b, int64_t *out, int site);
```

This means a fallible operation can no longer sit in the middle of a C
expression. Expressions are lowered to **one operation per statement**, each
fallible step followed by its check (functions.md, "Evaluation order and
lowering"). That lowering also closes the open gap in UB-catalogue row 9:
operands are evaluated strictly left to right, so the error reported is
always the first one in source order.

## 4. The error record and the trace

One record per program, filled when an error starts and read by `main`:

```c
static struct {
    scribe_err code;       /* R0001 ... */
    int site;              /* where it started: file, line, column, function */
    int frames[64];        /* call sites, innermost first */
    int depth;             /* how many calls the error passed through */
} scribe_error;
```

- A failing check or `raise` sets `code` and `site`, sets `depth` to 0,
  and returns non-zero.
- `scribe_trace(site)` appends the call site as the error passes through each
  caller.
- **Bounded.** If an error passes through more than 64 calls, the record
  keeps the innermost 32 and the outermost 32 and counts the rest, so a
  recursion-limit error still shows both ends.
- **One error at a time.** An error can't start while another is
  propagating, because propagation runs no user code. Exceptions are
  cleanups and `finally`; section 7 says what happens there.
- The record is a file-scope static, since v1 has no threads. With threads it
  becomes `_Thread_local`.

The site table that runtime errors already use (`scribe_sites`) grows to hold,
for each site, the file, line, column, enclosing function and the source
line's text. All of these are compile-time strings, so the traceback can show
source code without the program reading any files.

## 5. Traceback formats

**Text (default), on stderr.** The newest call is last, as in Python. The
last line keeps today's `file:line:col: runtime error: ...` form, so editors
and the existing tests still find it:

```text
Traceback (most recent call last):
  fact.scribe:8:7, in <program>
    print fact(25)
  fact.scribe:5:16, in fact
    return n * fact(n - 1)
  [the line above repeats 3 more times]
  fact.scribe:5:14, in fact
    return n * fact(n - 1)
fact.scribe:5:14: runtime error[R0001]: integer overflow
```

Identical consecutive frames are folded, as Python does for recursion. An
error with no calls between it and `main` prints only the last line, so
programs without functions look exactly as they do today.

**JSON, for tools and AI agents.** It is selected when the program runs,
with no recompiling:

- `SCRIBE_TRACEBACK=json` writes JSON to stderr instead of text.
- `SCRIBE_TRACEBACK_FILE=path` also writes the JSON to that file.

The environment is read only after an error has happened. It changes how an
error is *reported*, never what the program computes.

```json
{
  "error": {"code": "R0001", "name": "integer-overflow", "message": "integer overflow",
            "file": "fact.scribe", "line": 5, "column": 14, "function": "fact"},
  "traceback": [
    {"file": "fact.scribe", "line": 8, "column": 7, "function": "<program>", "source": "print fact(25)"},
    {"file": "fact.scribe", "line": 5, "column": 16, "function": "fact", "source": "return n * fact(n - 1)", "repeat": 4},
    {"file": "fact.scribe", "line": 5, "column": 14, "function": "fact", "source": "return n * fact(n - 1)"}
  ],
  "omitted": 0
}
```

The field names match the compiler's `--diagnostics-format json` wherever the
two overlap (`code`, `message`, `file`, `line`, `column`).

**Exit status.** 0 on success, and 1 for an uncaught runtime error, as in
Python. Today's 134 from `abort()` goes away; that is a visible change.

## 6. Recursion limit

Deep recursion overflows the C stack, which C does not define (UB-catalogue
row 17). Functions that are part of a cycle in the call graph count their
depth on entry. Past the limit, the call fails with R0005 like any other
runtime error, and the error comes with a traceback. The limit is 1,000
calls by default, Python's default, and `scribe --recursion-limit N` changes
it. That is a resource bound, like a stack size, so a program within the
limit behaves the same under any setting. A non-recursive function pays
nothing. Tail calls are not optimised in v1.

## 7. Later: `raise`, `try`, `except`, `finally`

The propagation model is what these build on; none of them is in the first
functions milestone.

```text
fn parse_digit(i64: c) -> i64 {
    if c < 48 or c > 57 {
        raise ValueError("not a digit")
    }
    return c - 48
}

try {
    d = parse_digit(code)
} except ValueError {
    d = 0
} finally {
    print "done"
}
```

- `raise E(...)` fills the error record and jumps to the function's error
  exit.
- Inside a `try` body, a failed check means `goto` the handler instead of
  `goto fail`. `except` compares the error's code; if nothing matches, the
  error keeps propagating.
- `finally` is a cleanup entry: it runs on every exit edge of the `try`
  (normal end, `return`, error).
- **Catching checks.** A bare `except` catches only raised errors (R01xx).
  The errors of the checks are caught only when named:
  `except OverflowError`, `except ZeroDivisionError`. A bug is never
  swallowed by accident, and a program that expects one says which.

```text
try {
    ratio = total // count
} except ZeroDivisionError {
    ratio = 0
}
```
- **Open:** an error raised inside `finally` while another is propagating.
  Python chains them; the simplest rule is to report the new error and attach
  the original as context.
- Error types with data (a message, a value) need strings, and later unions
  or classes. Until then an error is a code plus the place it started.

## 8. Decisions

Decided (2026-10-23):

1. Every runtime error propagates to `main`, checks included, with a
   traceback (section 2).
2. A bare `except` catches only raised errors. A check's error is caught
   only by name, such as `except OverflowError` (section 7).
3. The recursion limit is 1,000 by default, with `--recursion-limit` to
   change it (section 6).

Proposed, not yet confirmed:

- `scribe_err` is an integer, and the details live in one global record,
  instead of a returned struct (section 3).
- Exit status 1 instead of `abort()` (section 5).
- The trace keeps 64 frames (section 4).
- JSON is chosen with environment variables when the program runs (section 5).
- The error type names in section 1.

Open:

- An error raised inside `finally` while another one is propagating
  (section 7).
- Error types that carry data, which need strings and later unions or
  classes.
